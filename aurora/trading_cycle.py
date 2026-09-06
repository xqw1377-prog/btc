"""Decision cycle wired to the armed kernel.

Only TESTNET / armed LIVE should instantiate this. Orders go through
ArmedRuntime; this module never constructs a Binance Client.
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

import pandas as pd

from aurora.feature_engine import FeatureEngine
from aurora.kernel_types import Intent, TradeIntent
from aurora.market_state_engine_v2 import MarketStateEngineV2
from aurora.p0_boundary import RunMode, SafetyViolation
from aurora.portfolio_brain_v2 import PortfolioBrainV2
from aurora.signal_providers import (
    BreakoutSignalProvider,
    MeanReversionSignalProvider,
    MomentumSignalProvider,
    TrendSignalProvider,
)

MIN_QTY = 0.001
ENABLE_TOKEN = "true"


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
        self.brain = brain or PortfolioBrainV2(self.capital)

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
        regime = self.state_engine.identify_regime(feats)
        signals = [
            self.trend.generate(feats, regime["regime"]),
            self.breakout.generate(feats, df),
            self.momentum.generate(feats),
            self.mr.generate(feats),
        ]
        intent = self.brain.process(
            signals=signals,
            regime=regime["regime"],
            confidence=regime["confidence"],
            volatility=float(feats.get("volatility") or 0),
            price=float(feats["close"]),
            atr=float(feats.get("atr") or 0),
            current_ts=time.time(),
            features=feats,
        )
        return {
            "action": intent.action,
            "reason": intent.reason,
            "intent": intent,
            "features": feats,
            "regime": regime,
        }

    def sync_brain_from_exchange(self) -> None:
        pos = self.runtime.exchange.position(self.symbol)
        brain_pos = self.brain.position_mgr.position
        if pos is None:
            return
        if abs(pos.signed_qty) < 1e-12:
            if brain_pos.is_open:
                self.brain.position_mgr.close(pos.entry_price or brain_pos.entry_price, "exchange flat")
            return
        if not brain_pos.is_open:
            side = Intent.LONG if pos.signed_qty > 0 else Intent.SHORT
            self.brain.position_mgr.open(
                side, abs(pos.signed_qty), pos.entry_price, 0.0, 0.0, "sync from exchange")

    def execute(self, decision: Dict[str, Any], enable: bool) -> Dict[str, Any]:
        intent: Optional[TradeIntent] = decision.get("intent")
        feats = decision.get("features") or {}
        price = float(feats.get("close") or 0)
        if intent is None or intent.action == "HOLD":
            return {"submitted": False, "action": "HOLD", "reason": decision.get("reason")}
        if not enable:
            return {"submitted": False, "action": intent.action, "reason": "trading disabled; intent not sent"}
        if intent.action == "OPEN":
            if price <= 0:
                return {"submitted": False, "action": "HOLD", "reason": "invalid price"}
            qty = round(self.brain.capital * intent.size_pct / price, 3)
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
            return {"submitted": True, "action": "OPEN", "result": result, "qty": qty}
        if intent.action == "CLOSE":
            result = self.runtime.close_position(intent.reason)
            if result.get("success"):
                self.brain.execute_intent(intent, price)
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
        try:
            df = self.fetch_klines()
        except Exception as exc:
            return {"action": "HOLD", "reason": f"klines failed: {exc}", "recover": report}
        decision = self.decide(df)
        executed = self.execute(decision, enable)
        return {**executed, "recover": report, "decision_reason": decision.get("reason")}
