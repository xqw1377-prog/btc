"""E1 Risk Semantics — single authority for sizing, SL/TP, vol units, funding gates.

Contract:
- PortfolioBrainV2 proposes direction + ATR stop distance only.
- RiskGate is the final authority for size_pct, stop_loss_pct, take_profit_pct.
- Volatility consumed by risk layers is vol_atr_pct (ATR/price), not annualized 1m vol.
- Sizing primary path: risk_budget_pct / stop_distance_pct, capped by max_position_pct.
- Funding paid is ledger-authoritative (income_events); funding_rate is a read-only veto input.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

# Regime ATR multiples — brain proposes; RiskGate finalizes/clamps.
REGIME_SL_ATR_MULT = {"TREND": 2.0, "RANGE": 1.0, "TRANSITION": 1.5}
REGIME_TP_ATR_MULT = {"TREND": 3.0, "RANGE": 1.5, "TRANSITION": 2.0}

DEFAULT_RISK_BUDGET_PCT = 0.005  # 0.5% equity at risk per trade
MIN_STOP_PCT = 0.003
MAX_STOP_PCT = 0.08
MIN_TP_PCT = 0.004
MAX_TP_PCT = 0.15

# vol_atr_pct bands (ATR/close)
VOL_ATR_HIGH = 0.025
VOL_ATR_MID = 0.015


@dataclass(frozen=True)
class VolatilityUnits:
    """Normalized volatility for risk layers."""

    vol_atr_pct: float
    vol_daily: float
    legacy_annualized: float = 0.0

    @classmethod
    def from_features(cls, feats: Dict[str, Any]) -> "VolatilityUnits":
        close = float(feats.get("close") or 0.0)
        atr = float(feats.get("atr") or 0.0)
        vol_atr = float(feats.get("vol_atr_pct") or 0.0)
        if vol_atr <= 0 and close > 0 and atr > 0:
            vol_atr = atr / close
        vol_daily = float(feats.get("vol_daily") or 0.0)
        legacy = float(feats.get("volatility") or 0.0)
        return cls(
            vol_atr_pct=max(vol_atr, 0.0),
            vol_daily=max(vol_daily, 0.0),
            legacy_annualized=max(legacy, 0.0),
        )


def proposed_sl_tp_pct(
    regime: str, atr: float, price: float,
) -> Tuple[float, float]:
    """Brain-side ATR distance proposal (pct of price). Zero = unknown → Gate must deny OPEN."""
    if price <= 0 or atr <= 0:
        return 0.0, 0.0
    sl_mult = REGIME_SL_ATR_MULT.get(regime, REGIME_SL_ATR_MULT["TRANSITION"])
    tp_mult = REGIME_TP_ATR_MULT.get(regime, REGIME_TP_ATR_MULT["TRANSITION"])
    sl = (atr * sl_mult) / price
    tp = (atr * tp_mult) / price
    return sl, tp


def clamp_sl_tp(
    proposed_sl: float,
    proposed_tp: float,
    kernel_sl: float,
    kernel_tp: float,
) -> Tuple[float, float]:
    """RiskGate authority: ATR proposal with hard bounds; no silent fallback when SL unknown."""
    if proposed_sl <= 0:
        return 0.0, 0.0
    sl = proposed_sl
    tp = proposed_tp if proposed_tp > 0 else kernel_tp
    sl = max(MIN_STOP_PCT, min(sl, MAX_STOP_PCT))
    tp = max(MIN_TP_PCT, min(tp, MAX_TP_PCT))
    if tp <= sl:
        tp = min(MAX_TP_PCT, sl * 1.5)
    return round(sl, 6), round(tp, 6)


def size_pct_from_risk_budget(
    equity: float,
    stop_loss_pct: float,
    risk_budget_pct: float = DEFAULT_RISK_BUDGET_PCT,
    max_position_pct: float = 0.40,
) -> float:
    """risk_usdt / stop_distance → notional fraction of equity."""
    if equity <= 0 or stop_loss_pct <= 0:
        return 0.0
    raw = risk_budget_pct / stop_loss_pct
    return max(0.0, min(raw, max_position_pct))


def qty_from_authorized_intent(
    equity: float, size_pct: float, price: float, min_qty: float = 0.001,
    max_qty: Optional[float] = None,
) -> float:
    if price <= 0 or equity <= 0 or size_pct <= 0:
        return 0.0
    qty = round(equity * size_pct / price, 3)
    if max_qty is not None and qty > max_qty:
        qty = round(float(max_qty), 3)
    return max(0.0, qty)


def fetch_funding_rate(client: Any, symbol: str) -> Optional[float]:
    """Read-only funding rate; None if unavailable."""
    if client is None:
        return None
    try:
        if hasattr(client, "futures_funding_rate"):
            row = client.futures_funding_rate(symbol=symbol)
            if isinstance(row, dict):
                return float(row.get("lastFundingRate") or row.get("fundingRate") or 0)
        if hasattr(client, "futures_mark_price"):
            row = client.futures_mark_price(symbol=symbol)
            if isinstance(row, dict) and row.get("lastFundingRate") is not None:
                return float(row["lastFundingRate"])
    except Exception:
        return None
    return None


def estimate_spread_pct(feats: Dict[str, Any]) -> float:
    """Conservative spread proxy from bar range when bid/ask unavailable."""
    close = float(feats.get("close") or 0.0)
    if close <= 0:
        return 0.001
    atr = float(feats.get("atr") or 0.0)
    if atr > 0:
        return min(0.01, max(0.0001, (atr * 0.1) / close))
    return 0.001
