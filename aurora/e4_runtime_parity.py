"""E4 Runtime parity — production overlay thesis vs E3 on the same closed daily.

PAPER still cannot instantiate TradingCycle. Parity is proven on FakeExchange
with writes disabled. E4 does not retune E2/E1 and is not LIVE.

Contract:
    same closed daily prefix
    → same horizon close / ema / adx
    → same decide_overlay action
    even if the live frame still carries a forming daily bar.

OPEN is one-way: production may HOLD when E3 would OPEN (RiskGate).
Production must not OPEN when E3 says HOLD.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from aurora.e3_walkforward import DAY_MS, horizon_from_closed_slice
from aurora.feature_engine import FeatureEngine
from aurora.strategy_v2 import MIN_HORIZON_BARS, decide_overlay, horizon_from_frame

HORIZON_KEYS = ("close", "ema20", "ema60", "ema_slope", "adx", "atr", "vol_atr_pct")


def append_forming_bar(closed: pd.DataFrame) -> pd.DataFrame:
    """Simulate an exchange 1d frame that still includes today's unclosed bar."""
    if closed is None or len(closed) == 0:
        return closed
    last = closed.iloc[-1]
    row = last.copy()
    row["time"] = int(last["time"]) + DAY_MS
    row["open"] = float(last["close"])
    row["high"] = float(last["close"]) * 1.05
    row["low"] = float(last["close"]) * 0.95
    row["close"] = float(last["close"]) * 2.0  # would poison look-ahead if consumed
    if "volume" in closed.columns:
        row["volume"] = 0.0
    return pd.concat([closed, pd.DataFrame([row])], ignore_index=True)


def production_horizon(raw_1d: pd.DataFrame, engine: Optional[FeatureEngine] = None,
                       now_ms: Optional[int] = None):
    return horizon_from_frame(raw_1d, engine or FeatureEngine(), now_ms=now_ms)


def compare_prefix(closed_prefix: pd.DataFrame, overlay_open: bool) -> Dict[str, Any]:
    engine = FeatureEngine()
    last = int(closed_prefix["time"].iloc[-1])
    now_ms = last + DAY_MS  # during the next (forming) day
    e3 = horizon_from_closed_slice(closed_prefix, engine)
    live = production_horizon(append_forming_bar(closed_prefix), engine, now_ms=now_ms)
    d_e3 = decide_overlay(e3, overlay_open)
    d_live = decide_overlay(live, overlay_open)
    mismatches = []
    for key in HORIZON_KEYS:
        a, b = getattr(e3, key), getattr(live, key)
        if abs(float(a) - float(b)) > 1e-9:
            mismatches.append(key)
    return {
        "e3_action": d_e3.action,
        "live_action": d_live.action,
        "e3_complete": e3.complete,
        "live_complete": live.complete,
        "horizon_mismatch": mismatches,
        "ok": d_e3.action == d_live.action and not mismatches
              and e3.complete == live.complete,
    }


def scan_closed_frame(closed: pd.DataFrame, step: int = 1) -> List[Dict[str, Any]]:
    """Walk prefixes; overlay_open follows E3 thesis (no fill delay)."""
    rows = []
    overlay_open = False
    n = len(closed)
    start = MIN_HORIZON_BARS - 1
    if start < 0 or n <= start:
        return rows
    for i in range(start, n, step):
        prefix = closed.iloc[: i + 1].reset_index(drop=True)
        cmp_ = compare_prefix(prefix, overlay_open)
        cmp_["i"] = i
        rows.append(cmp_)
        if not cmp_["ok"]:
            break
        if cmp_["e3_action"] == "OPEN":
            overlay_open = True
        elif cmp_["e3_action"] == "CLOSE":
            overlay_open = False
    return rows
