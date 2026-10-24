"""P2-A Dual-Asset HTF Trend Truth — read-only, engine-authoritative.

Levels L0–L5 come from 1D HTF only. 4H/1H provide structure confirmation.
3m is execution observation — never substitutes missing HTF.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from aurora.feature_engine import FeatureEngine
from aurora.funding_truth import apply_funding_open_eligibility
from aurora.strategy_v2 import (
    HORIZON_INTERVAL,
    decide_overlay,
    horizon_from_frame,
    HorizonSnapshot,
    closed_daily_bars,
)

INTERVAL_MS = {
    "1d": 86_400_000,
    "4h": 14_400_000,
    "1h": 3_600_000,
    "3m": 180_000,
}

TF_API = {"1d": "1d", "4h": "4h", "1h": "1h", "3m": "3m"}
TF_CHART = {"1d": "1D", "4h": "4H", "1h": "1H", "3m": "3m"}
MIN_STRUCTURE_BARS = 60

CAP_PARTIAL = "PARTIAL"
CAP_PROPOSED = "PROPOSED"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def closed_bars(
    df: Optional[pd.DataFrame],
    interval: str,
    *,
    now_ms: Optional[int] = None,
) -> pd.DataFrame:
    if df is None or len(df) == 0:
        return df
    bar_ms = INTERVAL_MS.get(interval, INTERVAL_MS["1d"])
    now_ms = (
        int(now_ms)
        if now_ms is not None
        else int(datetime.now(timezone.utc).timestamp() * 1000)
    )
    times = df["time"].astype("int64")
    return df.loc[times + bar_ms <= now_ms].reset_index(drop=True)


def _structure_from_frame(
    df: Optional[pd.DataFrame],
    interval: str,
    engine: FeatureEngine,
    *,
    now_ms: Optional[int] = None,
) -> Tuple[str, Dict[str, Any]]:
    if df is None or len(df) == 0:
        return "UNKNOWN", {"complete": False, "reason": "frame missing"}
    closed = closed_bars(df, interval, now_ms=now_ms)
    if closed is None or len(closed) < MIN_STRUCTURE_BARS:
        n = 0 if closed is None else len(closed)
        return "UNKNOWN", {"complete": False, "reason": f"bars {n} < {MIN_STRUCTURE_BARS}"}
    feats = engine.get_latest_features(closed, exclude_forming=False)
    close = float(feats.get("close") or 0)
    ema20 = float(feats.get("ema20") or 0)
    ema60 = float(feats.get("ema60") or 0)
    if close <= 0 or ema20 <= 0 or ema60 <= 0:
        return "UNKNOWN", {"complete": False, "reason": "features incomplete"}
    slope = float(feats.get("ema_slope") or 0)
    if close > ema20 > ema60 and slope > 0:
        label = "BULL"
    elif close < ema20 or ema20 < ema60:
        label = "BEAR"
    else:
        label = "TRANSITION"
    return label, {
        "complete": True,
        "close": close,
        "ema20": ema20,
        "ema60": ema60,
        "adx": float(feats.get("adx") or 0),
        "reason": f"{interval} structure {label}",
    }


def _trend_level(horizon: HorizonSnapshot) -> Tuple[str, str, int, str]:
    """Return (direction, level_label, level_num, strength)."""
    if not horizon.complete:
        return ("UNKNOWN", "L0/5", 0, "UNKNOWN")
    if horizon.bullish_trend:
        if horizon.adx >= 35:
            return ("BULL", "L5/5", 5, "EXTREME")
        if horizon.adx >= 28:
            return ("BULL", "L4/5", 4, "STRONG")
        return ("BULL", "L3/5", 3, "CONFIRMED")
    if horizon.close > horizon.ema20 > 0:
        return ("BULL", "L2/5", 2, "WATCH")
    if horizon.thesis_broken:
        return ("BEAR", "L1/5", 1, "WEAK")
    return ("TRANSITION", "L1/5", 1, "WEAK")


def _volume_state(feats: Dict[str, Any]) -> str:
    vol = float(feats.get("volume") or 0)
    if vol <= 0:
        return "UNKNOWN"
    return "NORMAL"


def _chart_slot(
    klines: Optional[List[dict]],
    meta_status: str,
    *,
    role: str,
) -> Dict[str, Any]:
    if not klines:
        return {
            "status": "unknown",
            "role": role,
            "klines": [],
            "metrics": {},
            "connected": False,
        }
    df = pd.DataFrame(klines)
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = df[col].astype(float)
    engine = FeatureEngine()
    feats = engine.get_latest_features(df, exclude_forming=True)
    last = klines[-1]
    return {
        "status": meta_status if meta_status != "unknown" else "ok",
        "role": role,
        "klines": klines[-80:],
        "connected": True,
        "price": float(last.get("close") or 0),
        "metrics": {
            "price": f"${float(last.get('close') or 0):,.2f}",
            "ema20": f"{feats.get('ema20', 0):,.2f}" if feats.get("ema20") else "—",
            "ema60": f"{feats.get('ema60', 0):,.2f}" if feats.get("ema60") else "—",
            "adx": f"{feats.get('adx', 0):.1f}" if feats.get("adx") else "—",
        },
    }


def build_trend_snapshot(
    asset: str,
    klines_by_tf: Optional[Dict[str, List[dict]]],
    *,
    capability: str = CAP_PARTIAL,
    freshness: str = "ok",
    source: str = "dashboard_feed",
    funding: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build authoritative TrendSnapshot for one asset."""
    klines_by_tf = klines_by_tf or {}
    engine = FeatureEngine()

    df_1d = pd.DataFrame(klines_by_tf.get("1d") or [])
    if len(df_1d) and "time" in df_1d.columns:
        for col in ("open", "high", "low", "close", "volume"):
            if col in df_1d.columns:
                df_1d[col] = df_1d[col].astype(float)
        closed_1d = closed_daily_bars(df_1d)
        horizon = horizon_from_frame(closed_1d, engine)
    else:
        horizon = HorizonSnapshot(HORIZON_INTERVAL, False, reason="1D klines missing")

    direction, level, level_num, strength = _trend_level(horizon)

    h4_label, h4_meta = _structure_from_frame(
        pd.DataFrame(klines_by_tf.get("4h") or []) if klines_by_tf.get("4h") else None,
        "4h",
        engine,
    )
    h1_label, h1_meta = _structure_from_frame(
        pd.DataFrame(klines_by_tf.get("1h") or []) if klines_by_tf.get("1h") else None,
        "1h",
        engine,
    )

    blockers: List[str] = []
    reasons: List[str] = []
    if not horizon.complete:
        blockers.append(horizon.reason or "1D HTF incomplete")
    if h4_label == "BEAR":
        blockers.append("4H structure BEAR — overlay veto")
    if direction == "UNKNOWN":
        blockers.append("Trend direction UNKNOWN")

    trend_action = "BLOCKED"
    if horizon.complete and direction == "BULL" and level_num >= 3 and h4_label != "BEAR":
        trend_action = "LONG_ELIGIBLE"
        reasons.append("1D L3+ bullish · 4H not BEAR")
    elif horizon.complete and direction == "BULL" and level_num >= 2:
        trend_action = "WATCH"
        reasons.append("Trend forming · not yet L3 eligible")
    elif direction in ("BEAR", "TRANSITION"):
        trend_action = "HOLD"
        reasons.append(f"Direction {direction}")

    funding = funding or {}
    action, blockers = apply_funding_open_eligibility(
        trend_action, funding, blockers,
    )

    overlay = decide_overlay(horizon, overlay_open=False)
    if horizon.complete:
        reasons.append(overlay.reason)

    daily_feats = {}
    if horizon.complete:
        daily_feats = {
            "close": horizon.close,
            "ema20": horizon.ema20,
            "ema60": horizon.ema60,
            "adx": horizon.adx,
        }

    timeframes: Dict[str, Any] = {}
    for key, chart_tf in TF_CHART.items():
        role = "diagnostic" if key == "3m" else "authority" if key == "1d" else "confirmation"
        timeframes[chart_tf] = _chart_slot(
            klines_by_tf.get(key),
            freshness,
            role=role,
        )

    return {
        "asset": asset,
        "as_of": _now_iso(),
        "capability": capability,
        "trend_direction": direction,
        "trend_level": level,
        "trend_level_num": level_num,
        "trend_strength": strength,
        "daily_structure": "BULL" if horizon.bullish_trend else (
            "BEAR" if horizon.thesis_broken else "UNKNOWN" if not horizon.complete else "TRANSITION"
        ),
        "h4_structure": h4_label,
        "h1_structure": h1_label,
        "close": daily_feats.get("close"),
        "ema20": daily_feats.get("ema20"),
        "ema60": daily_feats.get("ema60"),
        "adx": daily_feats.get("adx"),
        "volume_state": _volume_state(h4_meta) if h4_meta.get("complete") else "UNKNOWN",
        "volatility_state": "KNOWN" if horizon.complete else "UNKNOWN",
        "funding_rate": funding.get("funding_rate"),
        "funding_observed_at": funding.get("funding_observed_at"),
        "funding_next_settlement_at": funding.get("funding_next_settlement_at"),
        "funding_source": funding.get("funding_source"),
        "funding_freshness": funding.get("funding_freshness", "unknown"),
        "funding_state": funding.get("funding_state", "UNKNOWN"),
        "oi_state": "UNKNOWN",
        "trend_action": trend_action,
        "action_eligibility": action,
        "reasons": reasons,
        "blockers": blockers,
        "source": source,
        "freshness": freshness,
        "timeframes": timeframes,
        # legacy compat fields
        "dir": direction,
        "level": level,
        "action": action,
        "evidence": "; ".join(blockers) if blockers else "; ".join(reasons[:2]) or "HTF observation",
    }


def relative_strength(
    btc: Dict[str, Any],
    eth: Dict[str, Any],
) -> Dict[str, Any]:
    btc_num = int(btc.get("trend_level_num") or 0)
    eth_num = int(eth.get("trend_level_num") or 0)
    btc_adx = float(btc.get("adx") or 0)
    eth_adx = float(eth.get("adx") or 0)

    if btc_num == 0 and eth_num == 0:
        label = "UNKNOWN"
    elif btc_num > eth_num or (btc_num == eth_num and btc_adx >= eth_adx):
        label = "BTC > ETH"
    elif eth_num > btc_num:
        label = "ETH > BTC"
    else:
        label = "BTC ≈ ETH"

    return {
        "label": label,
        "btc_level": btc.get("trend_level"),
        "eth_level": eth.get("trend_level"),
        "btc_adx": btc_adx,
        "eth_adx": eth_adx,
        "btc_vs_eth": (
            "STRONGER" if "BTC >" in label else "WEAKER" if "ETH >" in label else "NEUTRAL"
        ),
        "eth_vs_btc": (
            "STRONGER" if "ETH >" in label else "WEAKER" if "BTC >" in label else "NEUTRAL"
        ),
    }


def eligibility_display(action: str) -> str:
    mapping = {
        "ELIGIBLE": "LONG ELIGIBLE",
        "WATCH": "WATCH",
        "HOLD": "HOLD",
        "BLOCK_NEW_RISK": "BLOCK NEW RISK",
    }
    return mapping.get(action, action or "UNKNOWN")


def build_dual_asset_trend_truth(
    *,
    btc_klines_by_tf: Optional[Dict[str, List[dict]]] = None,
    eth_klines_by_tf: Optional[Dict[str, List[dict]]] = None,
    btc_funding: Optional[Dict[str, Any]] = None,
    eth_funding: Optional[Dict[str, Any]] = None,
    market_meta: Optional[dict] = None,
) -> Dict[str, Any]:
    freshness = (market_meta or {}).get("status", "unknown")
    btc = build_trend_snapshot(
        "BTC",
        btc_klines_by_tf,
        capability=CAP_PARTIAL,
        freshness=freshness,
        funding=btc_funding,
    )
    eth = build_trend_snapshot(
        "ETH",
        eth_klines_by_tf,
        capability=CAP_PARTIAL if eth_klines_by_tf else CAP_PROPOSED,
        freshness=freshness if eth_klines_by_tf else "unknown",
        funding=eth_funding,
    )
    rs = relative_strength(btc, eth)

    status = "ok" if btc.get("trend_level_num", 0) > 0 or btc.get("freshness") == "ok" else "unknown"
    if not btc_klines_by_tf or not btc_klines_by_tf.get("1d"):
        status = "unknown"

    return {
        "capability": CAP_PARTIAL,
        "status": status,
        "as_of": _now_iso(),
        "btc": btc,
        "eth": eth,
        "relative_strength": rs,
        "preferred": rs["label"] if rs["label"] != "UNKNOWN" else "UNKNOWN",
        "charts": {
            "btc": {
                "timeframes": btc["timeframes"],
                "timeframe": "3m",
                **btc["timeframes"].get("3m", {}),
            },
            "eth": {
                "timeframes": eth["timeframes"],
                "timeframe": "3m",
                **eth["timeframes"].get("3m", {}),
            },
        },
    }


def fetch_klines_by_tf(client: Any, symbol: str) -> Dict[str, List[dict]]:
    """Fetch 1D/4H/1H/3m klines for trend truth (read-only)."""
    from aurora.observatory_snapshots import fetch_klines_df, klines_records

    specs = [("1d", 1500, 80), ("4h", 500, 80), ("1h", 500, 80), ("3m", 80, 80)]
    out: Dict[str, List[dict]] = {}
    for interval, fetch_limit, tail in specs:
        try:
            df = fetch_klines_df(client, symbol, TF_API[interval], fetch_limit)
            out[interval] = klines_records(df, tail)
        except Exception:
            out[interval] = []
    return out
