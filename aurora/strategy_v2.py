"""E2 Strategy V2 — BTC-numeraire identity. Not an edge claim.

Why AURORA exists: hold more BTC over time than simply holding BTC.
That sentence is the product. It is not yet evidence.

```text
NUMERAIRE     = BTC
CORE SLEEVE   = HOLD BTC   (identity + E3 benchmark; not a 1m bot)
OVERLAY SLEEVE= BTCUSDT PERP LONG only, HTF-gated, RiskGate-sized
FORBIDDEN     = NET SHORT, 1m SIGNAL AUTHORITY, USDT-PnL as objective
STRATEGY EDGE = NO-EVIDENCE until E3 BTC-HODL walk-forward / OOS
```

V2-R0 execution honesty: the armed kernel still only writes BTCUSDT perp.
The core HODL sleeve is the economic identity and the benchmark, not a new
spot executor. Missing HTF data denies overlay OPEN; it does not block
risk-reducing CLOSE.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from aurora.feature_engine import FeatureEngine
from aurora.kernel_types import Intent

NUMERAIRE = "BTC"
CORE_POLICY = "HOLD_BTC"
OVERLAY_INSTRUMENT = "BTCUSDT_PERP"
HORIZON_INTERVAL = "1d"
MIN_HORIZON_BARS = 60
HORIZON_FETCH_LIMIT = 1500  # exchange max; same lookback E3 can consume
DAY_MS = 86_400_000
DAILY_ADX_MIN = 20.0
OVERLAY_SIGNAL_SIZE_PCT = 0.10

FORBIDDEN = frozenset({
    "NET_SHORT",
    "1M_SIGNAL_AUTHORITY",
    "USDT_PNL_OBJECTIVE",
    "ETH_PERP",
    "PAIR_TRADE",
})


@dataclass(frozen=True)
class HorizonSnapshot:
    interval: str
    complete: bool
    close: float = 0.0
    ema20: float = 0.0
    ema60: float = 0.0
    ema_slope: float = 0.0
    adx: float = 0.0
    atr: float = 0.0
    vol_atr_pct: float = 0.0
    bar_open_time: Optional[int] = None
    reason: str = ""

    @property
    def bullish_trend(self) -> bool:
        if not self.complete:
            return False
        return (
            self.close > self.ema20 > self.ema60
            and self.ema_slope > 0
            and self.adx >= DAILY_ADX_MIN
        )

    @property
    def thesis_broken(self) -> bool:
        if not self.complete:
            return False
        return self.close < self.ema20 or self.ema20 < self.ema60


@dataclass(frozen=True)
class StrategyDirective:
    sleeve: str
    action: str
    side: Intent
    thesis: str
    reason: str
    confidence: float
    htf_complete: bool
    overlay_atr: float = 0.0
    overlay_vol_atr_pct: float = 0.0
    signal_size_pct: float = 0.0

    @classmethod
    def core_hold(cls, reason: str, htf_complete: bool = False) -> "StrategyDirective":
        return cls(
            sleeve="CORE",
            action="HOLD",
            side=Intent.FLAT,
            thesis="HOLD_BTC",
            reason=reason,
            confidence=1.0,
            htf_complete=htf_complete,
        )


def closed_daily_bars(df: pd.DataFrame, now_ms: Optional[int] = None) -> pd.DataFrame:
    """Keep only daily bars whose close is already in the past (no forming bar)."""
    if df is None or len(df) == 0:
        return df
    now_ms = (
        int(now_ms)
        if now_ms is not None
        else int(datetime.now(timezone.utc).timestamp() * 1000)
    )
    times = df["time"].astype("int64")
    return df.loc[times + DAY_MS <= now_ms].reset_index(drop=True)


def horizon_from_frame(
    df: Optional[pd.DataFrame],
    engine: Optional[FeatureEngine] = None,
    *,
    now_ms: Optional[int] = None,
) -> HorizonSnapshot:
    """Build daily HTF snapshot from closed bars only.

    Forming bars are dropped by wall-clock (open + 1d <= now), not by blindly
    discarding the last row. Incomplete → fail-closed for overlay OPEN.
    """
    if df is None or len(df) == 0:
        return HorizonSnapshot(
            interval=HORIZON_INTERVAL, complete=False,
            reason="HTF frame missing",
        )
    engine = engine or FeatureEngine()
    closed = closed_daily_bars(df, now_ms=now_ms)
    if closed is None or len(closed) < MIN_HORIZON_BARS:
        n = 0 if closed is None else len(closed)
        return HorizonSnapshot(
            interval=HORIZON_INTERVAL, complete=False,
            reason=f"HTF bars {n} < {MIN_HORIZON_BARS}",
        )
    feats = engine.get_latest_features(closed, exclude_forming=False)
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


def decide_overlay(horizon: HorizonSnapshot, overlay_open: bool) -> StrategyDirective:
    """HTF is the only overlay authority. 1m signals are not consulted."""
    if not overlay_open and not horizon.complete:
        return StrategyDirective.core_hold(
            f"Overlay OPEN denied: {horizon.reason or 'HTF incomplete'}",
            htf_complete=False,
        )
    if overlay_open and horizon.thesis_broken:
        return StrategyDirective(
            sleeve="OVERLAY",
            action="CLOSE",
            side=Intent.FLAT,
            thesis="EXIT_OVERLAY",
            reason="HTF thesis broken; flatten overlay, keep BTC identity",
            confidence=1.0,
            htf_complete=True,
            overlay_atr=horizon.atr,
            overlay_vol_atr_pct=horizon.vol_atr_pct,
        )
    if not overlay_open and horizon.bullish_trend:
        return StrategyDirective(
            sleeve="OVERLAY",
            action="OPEN",
            side=Intent.LONG,
            thesis="OVERLAY_LONG",
            reason="HTF daily bullish; optional perp overlay vs BTC HODL",
            confidence=min(0.5 + (horizon.adx - DAILY_ADX_MIN) / 80.0, 0.9),
            htf_complete=True,
            overlay_atr=horizon.atr,
            overlay_vol_atr_pct=horizon.vol_atr_pct,
            signal_size_pct=OVERLAY_SIGNAL_SIZE_PCT,
        )
    if overlay_open:
        return StrategyDirective(
            sleeve="OVERLAY",
            action="HOLD",
            side=Intent.LONG,
            thesis="OVERLAY_LONG",
            reason="HTF thesis intact; maintain overlay",
            confidence=0.7,
            htf_complete=horizon.complete,
            overlay_atr=horizon.atr,
            overlay_vol_atr_pct=horizon.vol_atr_pct,
        )
    return StrategyDirective.core_hold(
        "Core HOLD BTC; overlay not eligible",
        htf_complete=horizon.complete,
    )


def reject_short(intent_side: Intent, action: str) -> bool:
    return action == "OPEN" and intent_side == Intent.SHORT
