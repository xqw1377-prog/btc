"""Decision cycle wired to the armed kernel.

Only TESTNET / armed LIVE should instantiate this. Orders go through
ArmedRuntime; this module never constructs a Binance Client.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional

import pandas as pd

from aurora.accounting_truth import (
    accounting_path_for_ledger,
    load_accounting,
    persist_accounting,
    rebuild_from_ledger,
    sync_brain_from_snapshot,
)
from aurora.feature_engine import FeatureEngine
from aurora.kernel_types import Intent, TradeIntent
from aurora.market_state_engine_v2 import MarketStateEngineV2
from aurora.p0_boundary import RunMode, SafetyViolation
from aurora.portfolio_brain_v2 import PortfolioBrainV2
from aurora.risk_semantics import (
    estimate_spread_pct,
    fetch_funding_rate,
    qty_from_authorized_intent,
)
from aurora.signal_providers import (
    BreakoutSignalProvider,
    MeanReversionSignalProvider,
    MomentumSignalProvider,
    TrendSignalProvider,
)

MIN_QTY = 0.001
ENABLE_TOKEN = "true"
KLINE_INTERVAL = "1m"


def default_evidence_path() -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "state", "strategy_evidence.json")


def trading_enabled(environ: Optional[Dict[str, str]] = None) -> bool:
    src = environ if environ is not None else os.environ
    return (src.get("AURORA_ENABLE_TRADING") or "").strip().lower() == ENABLE_TOKEN


def klines_to_frame(rows: Any) -> pd.DataFrame:
    df = pd.DataFrame(
        rows,
        columns=[
            "time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades",
            "taker_buy_base", "taker_buy_quote", "ignore",
        ],
    )
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    return df


class TradingCycle:
    def __init__(
        self,
        runtime,
        client: Any,
        symbol: str = "BTCUSDT",
        mode: Optional[RunMode] = None,
        brain: Optional[PortfolioBrainV2] = None,
        capital: float = 0.0,
        evidence_path: Optional[str] = None,
    ):
        if mode == RunMode.PAPER:
            raise SafetyViolation("[P0] PAPER cannot run a trading cycle.")
        if mode == RunMode.SHADOW:
            raise SafetyViolation("[P0] SHADOW is read-only; trading cycle forbidden.")
        self.runtime = runtime
        self.client = client
        self.symbol = symbol
        self.mode = mode
        self.features = FeatureEngine()
        self.state_engine = MarketStateEngineV2(confirmation_count=3)
        self.trend = TrendSignalProvider()
        self.breakout = BreakoutSignalProvider()
        self.momentum = MomentumSignalProvider()
        self.mr = MeanReversionSignalProvider()
        self.capital = capital or self._read_balance()
        self.initial_capital = self.capital
        self.brain = brain or PortfolioBrainV2(self.capital)
        ledger_path = getattr(getattr(runtime, "ledger", None), "path", "") or ""
        self.accounting_path = (
            accounting_path_for_ledger(ledger_path)
            if ledger_path
            else default_evidence_path().replace(
                "strategy_evidence.json", "accounting_truth.json")
        )
        self._last_applied_fill_id: Optional[str] = None
        cached = load_accounting(self.accounting_path)
        if cached and cached.last_applied_fill_id:
            self._last_applied_fill_id = cached.last_applied_fill_id
        self._sync_accounting(full_replay=cached is None)
        self.evidence_path = (
            evidence_path if evidence_path is not None else default_evidence_path()
        )
        # G0-2 重启去重：有持久化证据则武装两个引擎；
        # 无证据则保守处理——第一根 bar 只标记已见、不推进确认。
        self._evidence_armed = self._load_evidence()

    def _bar_id(self, feats: Dict[str, Any]):
        open_time = feats.get("bar_open_time")
        if open_time is None:
            return None
        return (self.symbol, KLINE_INTERVAL, int(open_time))

    def _load_evidence(self) -> bool:
        try:
            with open(self.evidence_path) as fh:
                data = json.load(fh)
        except Exception:
            return False
        bar_id = data.get("last_bar_id")
        if not (isinstance(bar_id, (list, tuple)) and len(bar_id) == 3):
            return False
        bar_id = (bar_id[0], bar_id[1], int(bar_id[2]))
        self.state_engine.mark_bar_seen(bar_id)
        self.brain.regime_memory.mark_bar_seen(bar_id)
        return True

    def _save_evidence(self, bar_id) -> None:
        try:
            os.makedirs(os.path.dirname(self.evidence_path) or ".", exist_ok=True)
            tmp = self.evidence_path + ".tmp"
            with open(tmp, "w") as fh:
                json.dump({"last_bar_id": list(bar_id)}, fh)
            os.replace(tmp, self.evidence_path)
        except Exception:
            pass  # 持久化失败不中断循环；代价是重启后保守跳过一根 bar

    def _arm_evidence(self, bar_id) -> None:
        self.state_engine.mark_bar_seen(bar_id)
        self.brain.regime_memory.mark_bar_seen(bar_id)
        self._evidence_armed = True
        if bar_id is not None:
            self._save_evidence(bar_id)

    def _read_balance(self) -> float:
        try:
            account = self.client.futures_account()
        except Exception:
            return 0.0
        for asset in account.get("assets") or []:
            if asset.get("asset") == "USDT":
                return float(asset.get("availableBalance") or 0)
        return 0.0

    def fetch_klines(self, limit: int = 120) -> pd.DataFrame:
        rows = self.client.futures_klines(symbol=self.symbol, interval="1m", limit=limit)
        return klines_to_frame(rows)

    def decide(self, df: pd.DataFrame) -> Dict[str, Any]:
        feats = self.features.get_latest_features(df, exclude_forming=True)
        if not feats or not feats.get("close"):
            return {"action": "HOLD", "reason": "no closed-bar features", "intent": None, "features": feats}
        # G0-2：两层确认/时长只消费同一个唯一已收盘 bar 证据。
        bar_id = self._bar_id(feats)
        if not self._evidence_armed:
            # 重启且无持久化证据：保守处理——第一根 bar 只标记已见，不推进。
            self._arm_evidence(bar_id)
            bar_id = None
        regime = self.state_engine.identify_regime(feats, bar_id=bar_id)
        signals = [
            self.trend.generate(feats, regime["regime"]),
            self.breakout.generate(feats, df),
            self.momentum.generate(feats),
            self.mr.generate(feats),
        ]
        funding_rate = fetch_funding_rate(self.client, self.symbol)
        if funding_rate is None:
            funding_rate = 0.0
        spread_pct = estimate_spread_pct(feats)
        intent = self.brain.process(
            signals=signals,
            regime=regime["regime"],
            confidence=regime["confidence"],
            volatility=float(feats.get("volatility") or 0),
            price=float(feats["close"]),
            atr=float(feats.get("atr") or 0),
            current_ts=time.time(),
            features=feats,
            bar_id=bar_id,
            funding_rate=funding_rate,
            spread_pct=spread_pct,
        )
        if bar_id is not None and regime.get("bar_status") == "NEW_CLOSED_BAR":
            self._save_evidence(bar_id)
        return {
            "action": intent.action,
            "reason": intent.reason,
            "intent": intent,
            "features": feats,
            "regime": regime,
            "bar_id": bar_id,
            "bar_status": regime.get("bar_status"),
        }

    def _sync_accounting(self, *, full_replay: bool = False) -> None:
        ledger = getattr(self.runtime, "ledger", None)
        if ledger is None or not hasattr(ledger, "list_economic_fills_with_context"):
            return
        snapshot = rebuild_from_ledger(ledger, self.initial_capital)
        watermark = None if full_replay else self._last_applied_fill_id
        self._last_applied_fill_id = sync_brain_from_snapshot(
            self.brain, snapshot, ledger, watermark)
        snapshot.last_applied_fill_id = self._last_applied_fill_id
        persist_accounting(snapshot, self.accounting_path)
        self.capital = snapshot.equity
        self.brain.risk_gate.funding_incomplete = bool(snapshot.funding_incomplete)

    def _sync_funding_events(self) -> None:
        """Best-effort pull of funding income into ledger; fail-closed for OPEN only."""
        ledger = getattr(self.runtime, "ledger", None)
        if ledger is None or not hasattr(ledger, "insert_income_event"):
            return
        if self.client is None or not hasattr(self.client, "futures_income_history"):
            return
        self.brain.risk_gate.funding_incomplete = False
        try:
            start_ms = ledger.max_income_time_ms("FUNDING_FEE") + 1
            rows = self.client.futures_income_history(
                symbol=self.symbol,
                incomeType="FUNDING_FEE",
                startTime=start_ms,
                limit=1000,
            )
            for row in rows or []:
                income_id = f"{row.get('tranId')}:{row.get('time')}:{self.symbol}"
                ledger.insert_income_event(
                    income_id=income_id,
                    symbol=self.symbol,
                    income_type="FUNDING_FEE",
                    amount=float(row.get("income") or 0.0),
                    time_ms=int(row.get("time") or 0),
                    asset=str(row.get("asset") or "USDT"),
                )
        except Exception:
            self.brain.risk_gate.funding_incomplete = True

    def sync_brain_from_exchange(self) -> None:
        pos = self.runtime.exchange.position(self.symbol)
        brain_pos = self.brain.position_mgr.position
        if pos is None:
            return
        if abs(pos.signed_qty) < 1e-12:
            if brain_pos.is_open:
                self.brain.close_position_from_accounting("exchange flat")
                self._sync_accounting()
            return
        if not brain_pos.is_open:
            side = Intent.LONG if pos.signed_qty > 0 else Intent.SHORT
            # 恢复同步的仓位没有可信保护证据：阈值 UNKNOWN，不参与价格触发，
            # 且不得用本地历史 trailing 值回填。
            self.brain.position_mgr.open(
                side, abs(pos.signed_qty), pos.entry_price, None, None,
                "sync from exchange",
                stop_loss_source="EXCHANGE_SYNC",
                protection_note="POSITION_RECOVERED_PROTECTION_UNKNOWN",
            )

    def execute(self, decision: Dict[str, Any], enable: bool) -> Dict[str, Any]:
        intent: Optional[TradeIntent] = decision.get("intent")
        feats = decision.get("features") or {}
        price = float(feats.get("close") or 0)
        if intent is None or intent.action == "HOLD":
            return {"submitted": False, "action": "HOLD", "reason": decision.get("reason")}
        if not enable:
            return {"submitted": False, "action": intent.action, "reason": "trading disabled; intent not sent"}
        if intent.action == "OPEN":
            if self.brain.risk_gate.funding_incomplete:
                return {"submitted": False, "action": "HOLD", "reason": "funding ledger incomplete"}
            if price <= 0:
                return {"submitted": False, "action": "HOLD", "reason": "invalid price"}
            qty = qty_from_authorized_intent(self.brain.capital, intent.size_pct, price, MIN_QTY)
            if qty < MIN_QTY:
                return {"submitted": False, "action": "HOLD", "reason": "size below minimum"}
            sl = price * (1 - intent.stop_loss_pct) if intent.side == Intent.LONG else price * (1 + intent.stop_loss_pct)
            tp = price * (1 + intent.take_profit_pct) if intent.side == Intent.LONG else price * (1 - intent.take_profit_pct)
            result = self.runtime.open_position(
                intent.side.value, qty,
                stop_price=round(sl, 2), take_profit_price=round(tp, 2),
                reason=intent.reason,
            )
            if result.get("success"):
                self.brain.execute_intent(intent, price)
                self._sync_accounting()
            return {"submitted": True, "action": "OPEN", "result": result, "qty": qty}
        if intent.action == "CLOSE":
            result = self.runtime.close_position(intent.reason)
            if result.get("success"):
                self.brain.execute_intent(intent, price)
                self._sync_accounting()
            return {"submitted": True, "action": "CLOSE", "result": result}
        return {"submitted": False, "action": intent.action, "reason": intent.reason}

    def step(self, enable: Optional[bool] = None) -> Dict[str, Any]:
        enable = trading_enabled() if enable is None else enable
        report = self.runtime.recover()
        if report.get("unresolved"):
            return {"action": "HOLD", "reason": "recover unresolved; new opens forbidden", "recover": report}
        if self.runtime.ledger.kill_state().get("engaged"):
            return {"action": "HOLD", "reason": "kill switch engaged", "recover": report}
        self.sync_brain_from_exchange()
        self._sync_funding_events()
        self._sync_accounting()
        try:
            df = self.fetch_klines()
        except Exception as exc:
            return {"action": "HOLD", "reason": f"klines failed: {exc}", "recover": report}
        decision = self.decide(df)
        executed = self.execute(decision, enable)
        return {**executed, "recover": report, "decision_reason": decision.get("reason")}
