"""E3 Walk-forward / OOS — frozen Strategy V2 vs BTC HODL.

First principle (immovable):
    E2 parameters are frozen before any OOS number is inspected.
    OOS is a verdict, not a tuner. This module must not write back into
    strategy_v2 / risk_semantics constants.

Economics:
    CORE = 1.0 BTC held throughout (the HODL identity and the benchmark).
    OVERLAY = optional USDT-margined BTCUSDT perp LONG.
    strategy_btc = 1.0 + overlay_usdt / price
    excess_btc = strategy_btc - 1.0

No look-ahead: decision on closed bar t executes at bar t+1 open.
Intrabar stop uses that bar's low (conservative for longs).

Public historical klines are read-only market data, not exchange writes.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from aurora.feature_engine import FeatureEngine
from aurora.risk_kernel import RiskLimits
from aurora.risk_semantics import (
    DEFAULT_RISK_BUDGET_PCT,
    clamp_sl_tp,
    proposed_sl_tp_pct,
    size_pct_from_risk_budget,
)
from aurora.strategy_v2 import (
    HORIZON_INTERVAL,
    MIN_HORIZON_BARS,
    OVERLAY_SIGNAL_SIZE_PCT,
    HorizonSnapshot,
    decide_overlay,
    horizon_from_frame,
)

# Frozen cost assumptions — not optimizable from OOS.
FROZEN_TAKER_FEE = 0.0004
FROZEN_SLIPPAGE = 0.0005
FUNDING_PRINTS_PER_DAY = 3.0
CORE_BTC = 1.0
DAY_MS = 86_400_000
MAX_FUNDING_RATE = RiskLimits().max_funding_rate_pct
MAX_POSITION_PCT = RiskLimits().max_position_pct

MIN_TRADES = 10
MIN_POSITIVE_FOLD_FRAC = 0.50
MAX_MONTH_SHARE = 0.50
MAX_TRADE_SHARE = 0.40


@dataclass
class FrozenCosts:
    taker_fee: float = FROZEN_TAKER_FEE
    slippage: float = FROZEN_SLIPPAGE
    funding_prints_per_day: float = FUNDING_PRINTS_PER_DAY
    risk_budget_pct: float = DEFAULT_RISK_BUDGET_PCT
    overlay_signal_size_pct: float = OVERLAY_SIGNAL_SIZE_PCT
    max_position_pct: float = MAX_POSITION_PCT
    max_funding_rate: float = MAX_FUNDING_RATE


@dataclass
class TradeRecord:
    open_time: int
    close_time: int
    entry: float
    exit: float
    qty: float
    pnl_usdt: float
    fees: float
    funding: float
    reason: str


@dataclass
class WalkforwardResult:
    hodl_btc: float
    strategy_btc: float
    excess_btc: float
    fees_usdt: float
    funding_usdt: float
    slippage_usdt: float
    n_trades: int
    turnover_notional: float
    folds: List[Dict[str, Any]]
    monthly_excess_btc: Dict[str, float]
    max_month_share: float
    max_trade_share: float
    positive_fold_frac: float
    verdict: str
    verdict_reasons: List[str]
    frozen_costs: Dict[str, float]
    look_ahead: str = "decision_on_close_t_fill_at_open_t_plus_1"
    numeraire: str = "BTC"
    edge_claim: str = "NO-EVIDENCE"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _assert_e2_frozen(costs: FrozenCosts) -> None:
    if costs.overlay_signal_size_pct != OVERLAY_SIGNAL_SIZE_PCT:
        raise ValueError("E3 forbidden: overlay size retune")
    if costs.risk_budget_pct != DEFAULT_RISK_BUDGET_PCT:
        raise ValueError("E3 forbidden: risk-budget retune")


def horizon_from_closed_slice(df: pd.DataFrame, engine: FeatureEngine) -> HorizonSnapshot:
    """Historical bars in the slice are already closed; do not drop the last one."""
    if df is None or len(df) == 0:
        return horizon_from_frame(None, engine)
    if len(df) < MIN_HORIZON_BARS:
        return HorizonSnapshot(
            interval=HORIZON_INTERVAL, complete=False,
            reason=f"HTF bars {len(df)} < {MIN_HORIZON_BARS}",
        )
    feats = engine.get_latest_features(df, exclude_forming=False)
    close = float(feats.get("close") or 0.0)
    ema20 = float(feats.get("ema20") or 0.0)
    ema60 = float(feats.get("ema60") or 0.0)
    atr = float(feats.get("atr") or 0.0)
    if close <= 0 or ema20 <= 0 or ema60 <= 0 or atr <= 0:
        return HorizonSnapshot(
            interval=HORIZON_INTERVAL, complete=False,
            reason="HTF features incomplete",
        )
    return HorizonSnapshot(
        interval=HORIZON_INTERVAL,
        complete=True,
        close=close,
        ema20=ema20,
        ema60=ema60,
        ema_slope=float(feats.get("ema_slope") or 0.0),
        adx=float(feats.get("adx") or 0.0),
        atr=atr,
        vol_atr_pct=float(feats.get("vol_atr_pct") or 0.0),
        bar_open_time=feats.get("bar_open_time"),
        reason="HTF daily closed bar",
    )


def simulate_overlay(
    df: pd.DataFrame,
    costs: Optional[FrozenCosts] = None,
) -> Tuple[WalkforwardResult, List[TradeRecord], pd.DataFrame]:
    costs = costs or FrozenCosts()
    _assert_e2_frozen(costs)
    engine = FeatureEngine()
    work = df.copy().reset_index(drop=True)
    if "funding_rate" not in work.columns:
        work["funding_rate"] = 0.0

    overlay_qty = 0.0
    entry = 0.0
    stop = 0.0
    take = 0.0
    realized_usdt = 0.0
    fees = 0.0
    funding_paid = 0.0
    slip_paid = 0.0
    pending: Optional[str] = None
    pending_sl = 0.0
    pending_tp = 0.0
    trades: List[TradeRecord] = []
    open_time = 0
    equity_curve_btc: List[float] = []
    decision_times: List[int] = []

    def mark_btc(price: float, qty: float, last_entry: float) -> float:
        upnl = qty * (price - last_entry) if qty > 0 else 0.0
        return CORE_BTC + (realized_usdt + upnl) / price

    def close_overlay(px: float, ts: int, reason: str) -> None:
        nonlocal overlay_qty, realized_usdt, fees, slip_paid, entry, stop, take
        if overlay_qty <= 0:
            return
        notional = overlay_qty * px
        slip = notional * costs.slippage
        fee = notional * costs.taker_fee
        pnl = overlay_qty * (px - entry) - fee - slip
        realized_usdt += pnl
        fees += fee
        slip_paid += slip
        trades.append(TradeRecord(
            open_time=open_time, close_time=ts, entry=entry, exit=px,
            qty=overlay_qty, pnl_usdt=pnl, fees=fee, funding=0.0, reason=reason,
        ))
        overlay_qty = 0.0
        entry = stop = take = 0.0

    n = len(work)
    for i in range(n):
        row = work.iloc[i]
        o = float(row["open"])
        h = float(row["high"])
        low = float(row["low"])
        c = float(row["close"])
        ts = int(row["time"])
        fr = float(row.get("funding_rate") or 0.0)

        if pending == "OPEN" and overlay_qty <= 0:
            px = o * (1.0 + costs.slippage)
            if pending_sl > 0 and fr <= costs.max_funding_rate:
                equity_usdt = CORE_BTC * px + realized_usdt
                size_pct = size_pct_from_risk_budget(
                    equity_usdt, pending_sl, costs.risk_budget_pct,
                    costs.max_position_pct)
                size_pct = min(size_pct, costs.overlay_signal_size_pct,
                               costs.max_position_pct)
                qty = equity_usdt * size_pct / px if px > 0 else 0.0
                if qty > 0:
                    notional = qty * px
                    fee = notional * costs.taker_fee
                    slip = notional * costs.slippage
                    fees += fee
                    slip_paid += slip
                    realized_usdt -= fee + slip
                    overlay_qty = qty
                    entry = px
                    stop = px * (1.0 - pending_sl)
                    take = px * (1.0 + pending_tp) if pending_tp > 0 else 0.0
                    open_time = ts
        elif pending == "CLOSE" and overlay_qty > 0:
            close_overlay(o * (1.0 - costs.slippage), ts, "htf_exit")
        pending = None

        if overlay_qty > 0:
            notional = overlay_qty * c
            fund = notional * fr * costs.funding_prints_per_day
            if fund:
                realized_usdt -= fund
                funding_paid += fund
            if stop > 0 and low <= stop:
                close_overlay(stop * (1.0 - costs.slippage), ts, "stop")
            elif take > 0 and h >= take:
                close_overlay(take * (1.0 - costs.slippage), ts, "take_profit")

        closed = work.iloc[: i + 1]
        horizon = horizon_from_closed_slice(closed, engine)
        directive = decide_overlay(horizon, overlay_qty > 0)
        if directive.action == "OPEN" and overlay_qty <= 0 and i + 1 < n:
            sl_pct, tp_pct = proposed_sl_tp_pct("TREND", horizon.atr, horizon.close)
            sl_pct, tp_pct = clamp_sl_tp(sl_pct, tp_pct, sl_pct, tp_pct)
            if sl_pct > 0 and fr <= costs.max_funding_rate:
                pending = "OPEN"
                pending_sl = sl_pct
                pending_tp = tp_pct
        elif directive.action == "CLOSE" and overlay_qty > 0 and i + 1 < n:
            pending = "CLOSE"

        equity_curve_btc.append(mark_btc(c, overlay_qty, entry))
        decision_times.append(ts)

    if overlay_qty > 0:
        last = work.iloc[-1]
        close_overlay(float(last["close"]) * (1.0 - costs.slippage),
                      int(last["time"]), "eod_flatten")

    curve = pd.DataFrame({"time": decision_times, "strategy_btc": equity_curve_btc})
    end_px = float(work.iloc[-1]["close"])
    strategy_btc = CORE_BTC + realized_usdt / end_px if end_px > 0 else CORE_BTC
    excess = strategy_btc - CORE_BTC
    folds = _year_folds(work, curve, trades)
    monthly = _monthly_excess(work, curve)
    pos_months = {k: v for k, v in monthly.items() if v > 0}
    month_share = (
        max(pos_months.values()) / sum(pos_months.values()) if pos_months else 0.0
    )
    pos_trades = [t.pnl_usdt for t in trades if t.pnl_usdt > 0]
    trade_share = (
        max(pos_trades) / sum(pos_trades) if pos_trades else 0.0
    )
    fold_pos = [1.0 if f["excess_btc"] > 0 else 0.0 for f in folds] or [0.0]
    pos_frac = sum(fold_pos) / len(fold_pos)
    verdict, reasons, claim = _verdict(
        excess, len(trades), pos_frac, month_share, trade_share)
    turnover = sum(abs(t.qty * t.entry) + abs(t.qty * t.exit) for t in trades)
    return WalkforwardResult(
        hodl_btc=CORE_BTC,
        strategy_btc=round(strategy_btc, 10),
        excess_btc=round(excess, 10),
        fees_usdt=round(fees, 8),
        funding_usdt=round(funding_paid, 8),
        slippage_usdt=round(slip_paid, 8),
        n_trades=len(trades),
        turnover_notional=round(turnover, 4),
        folds=folds,
        monthly_excess_btc={k: round(v, 10) for k, v in monthly.items()},
        max_month_share=round(month_share, 6),
        max_trade_share=round(trade_share, 6),
        positive_fold_frac=round(pos_frac, 6),
        verdict=verdict,
        verdict_reasons=reasons,
        frozen_costs=asdict(costs),
        edge_claim=claim,
    ), trades, curve


def _year_folds(work: pd.DataFrame, curve: pd.DataFrame,
                trades: List[TradeRecord]) -> List[Dict[str, Any]]:
    out = []
    times = pd.to_datetime(work["time"], unit="ms", utc=True)
    years = sorted(set(times.dt.year))
    for y in years:
        mask = times.dt.year == y
        if int(mask.sum()) < 5:
            continue
        idx = list(work.index[mask])
        start_i, end_i = int(idx[0]), int(idx[-1])
        btc0 = float(curve.iloc[start_i]["strategy_btc"])
        btc1 = float(curve.iloc[end_i]["strategy_btc"])
        out.append({
            "fold": str(y),
            "excess_btc": round(btc1 - btc0, 10),
            "n_bars": int(mask.sum()),
            "n_trades": sum(
                1 for t in trades
                if pd.Timestamp(t.open_time, unit="ms", tz="UTC").year == y
            ),
        })
    return out


def _monthly_excess(work: pd.DataFrame, curve: pd.DataFrame) -> Dict[str, float]:
    times = pd.to_datetime(work["time"], unit="ms", utc=True)
    monthly: Dict[str, float] = {}
    prev = CORE_BTC
    for i, ts in enumerate(times):
        key = ts.strftime("%Y-%m")
        btc = float(curve.iloc[i]["strategy_btc"]) if i < len(curve) else prev
        monthly[key] = monthly.get(key, 0.0) + (btc - prev)
        prev = btc
    return monthly


def _verdict(excess: float, n_trades: int, pos_frac: float,
             month_share: float, trade_share: float) -> Tuple[str, List[str], str]:
    reasons = []
    if n_trades < MIN_TRADES:
        reasons.append(f"trades {n_trades} < {MIN_TRADES}")
    if excess <= 0:
        reasons.append(f"excess_btc {excess:.6f} <= 0")
    if pos_frac < MIN_POSITIVE_FOLD_FRAC:
        reasons.append(f"positive_fold_frac {pos_frac:.2f} < {MIN_POSITIVE_FOLD_FRAC}")
    if month_share > MAX_MONTH_SHARE and excess > 0:
        reasons.append(f"max_month_share {month_share:.2f} > {MAX_MONTH_SHARE}")
    if trade_share > MAX_TRADE_SHARE and excess > 0:
        reasons.append(f"max_trade_share {trade_share:.2f} > {MAX_TRADE_SHARE}")
    if not reasons:
        return "EDGE_PASS_OFFLINE", ["all robustness gates passed"], "OFFLINE-OOS-ONLY"
    if excess <= 0:
        return "NEGATIVE_EXCESS", reasons, "NO-EVIDENCE"
    return "INSUFFICIENT_OR_CONCENTRATED", reasons, "NO-EVIDENCE"


def closed_daily_bars(df: pd.DataFrame, now_ms: Optional[int] = None) -> pd.DataFrame:
    """Keep only daily bars whose close is already in the past (no forming bar)."""
    now_ms = (
        int(now_ms)
        if now_ms is not None
        else int(datetime.now(timezone.utc).timestamp() * 1000)
    )
    times = df["time"].astype("int64")
    return df.loc[times + DAY_MS <= now_ms].reset_index(drop=True)


def load_ohlc_csv(path: str) -> Optional[pd.DataFrame]:
    """Load a local closed daily frame. No network. Host strings stay out of aurora/."""
    if not path or not os.path.isfile(path):
        return None
    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    need = {"time", "open", "high", "low", "close"}
    if not need.issubset(df.columns):
        return None
    if "volume" not in df.columns:
        df["volume"] = 0.0
    if "funding_rate" not in df.columns:
        df["funding_rate"] = 0.0
    return closed_daily_bars(df.sort_values("time").reset_index(drop=True))


def write_verdict(result: WalkforwardResult, path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = result.to_dict()
    payload["written_at"] = datetime.now(timezone.utc).isoformat()
    payload["note"] = (
        "OOS verdict only. Frozen E2. Not LIVE. Not a license to retune."
    )
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(root, "evidence", "e3", "verdict.json")
    csv_path = os.environ.get(
        "E3_OHLC_CSV", os.path.join(root, "evidence", "e3", "btcusdt_1d.csv"))
    df = load_ohlc_csv(csv_path)
    if df is None or len(df) < MIN_HORIZON_BARS + 10:
        write_verdict(WalkforwardResult(
            hodl_btc=CORE_BTC, strategy_btc=CORE_BTC, excess_btc=0.0,
            fees_usdt=0.0, funding_usdt=0.0, slippage_usdt=0.0, n_trades=0,
            turnover_notional=0.0, folds=[], monthly_excess_btc={},
            max_month_share=0.0, max_trade_share=0.0, positive_fold_frac=0.0,
            verdict="NOT-RUN",
            verdict_reasons=["local OHLC CSV missing or too short"],
            frozen_costs=asdict(FrozenCosts()),
            edge_claim="NO-EVIDENCE",
        ), out)
        print("E3 NOT-RUN: local OHLC CSV missing")
        return 0
    result, _, _ = simulate_overlay(df)
    write_verdict(result, out)
    print(json.dumps({
        "verdict": result.verdict,
        "edge_claim": result.edge_claim,
        "excess_btc": result.excess_btc,
        "n_trades": result.n_trades,
        "path": out,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
