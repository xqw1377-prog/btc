"""P2-B.1 ETH/BTC Value Truth — read-only relative value coordinates.

R = ETHUSDT_close / BTCUSDT_close on aligned closed bars (same venue, same bar time).
This is a **research / allocation ratio**, NOT a tradable ETHBTC executable price.

FROZEN:
  VALUE_ZONE != ALLOCATION_TRIGGER  (allocation is P2-B.2 / P3)
  LIVE snapshots MUST NOT include ex-post cycle progress or future peak fields.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from aurora.strategy_v2 import DAY_MS

CAP_PARTIAL = "PARTIAL"
CAP_PROPOSED = "PROPOSED"

SOURCE_SYNTHETIC_USDT = "SYNTHETIC_USDT_RATIO"
MIN_HISTORY_BARS = 60
CYCLE_LOOKBACK_BARS = 500

# PROVISIONAL_E3_PARAM — bands frozen as mechanism, not Alpha truth
_ZONE_BANDS: Tuple[Tuple[float, str], ...] = (
    (0.15, "DEEP_CHEAP_ETH"),
    (0.30, "CHEAP_ETH"),
    (0.70, "FAIR"),
    (0.85, "EXPENSIVE_ETH"),
    (1.00, "EXTREME_EXPENSIVE_ETH"),
)

# Live / decision snapshots MUST NOT carry ex-post-only fields (A5 / contract V1.1)
FORBIDDEN_LIVE_FIELDS = frozenset({
    "ex_post_cycle_progress",
    "cycle_high_final",
    "cycle_progress_pct",
    "distance_to_final_top",
    "distance_to_final_bottom",
    "full_cycle_completion_pct",
})


class LookaheadViolation(ValueError):
    """Raised when future data would leak into a live value snapshot."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _klines_to_map(klines: Optional[List[dict]]) -> Dict[int, float]:
    out: Dict[int, float] = {}
    if not klines:
        return out
    for row in klines:
        t = int(row["time"])
        close = float(row["close"])
        if close > 0:
            out[t] = close
    return out


def align_eth_btc_ratio_series(
    btc_klines: Optional[List[dict]],
    eth_klines: Optional[List[dict]],
    *,
    interval_ms: int = DAY_MS,
    now_ms: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Build aligned ratio bars; only includes bars fully closed at now_ms."""
    now_ms = int(now_ms) if now_ms is not None else _now_ms()
    btc = _klines_to_map(btc_klines)
    eth = _klines_to_map(eth_klines)
    times = sorted(set(btc) & set(eth))
    bars: List[Dict[str, Any]] = []
    for t in times:
        if t + interval_ms > now_ms:
            continue
        b_close = btc[t]
        e_close = eth[t]
        if b_close <= 0:
            continue
        bars.append({
            "time": t,
            "btc_close": b_close,
            "eth_close": e_close,
            "ratio": e_close / b_close,
        })
    return bars


def classify_value_zone(historical_percentile: Optional[float]) -> str:
    if historical_percentile is None:
        return "UNKNOWN"
    p = float(historical_percentile)
    for bound, zone in _ZONE_BANDS:
        if p <= bound:
            return zone
    return "EXTREME_EXPENSIVE_ETH"


def _percentile_rank(value: float, series: Sequence[float]) -> Optional[float]:
    if not series:
        return None
    below = sum(1 for x in series if x < value)
    equal = sum(1 for x in series if x == value)
    return (below + 0.5 * equal) / len(series)


def _cycle_window(ratios: Sequence[float], lookback: int = CYCLE_LOOKBACK_BARS) -> Tuple[int, int]:
    """Return [start_idx, end_idx) for current known cycle (trailing lookback)."""
    if not ratios:
        return 0, 0
    start = max(0, len(ratios) - lookback)
    window = ratios[start:]
    if not window:
        return start, len(ratios)
    trough_off = min(range(len(window)), key=lambda i: window[i])
    cycle_start = start + trough_off
    return cycle_start, len(ratios)


def _relative_trend(ratios: Sequence[float]) -> str:
    if len(ratios) < 20:
        return "UNKNOWN"
    recent = ratios[-20:]
    older = ratios[-40:-20] if len(ratios) >= 40 else ratios[: max(1, len(ratios) - 20)]
    if not older:
        return "UNKNOWN"
    r_now = sum(recent) / len(recent)
    r_old = sum(older) / len(older)
    if r_old <= 0:
        return "UNKNOWN"
    delta = (r_now - r_old) / r_old
    if delta > 0.01:
        return "IMPROVING"
    if delta < -0.01:
        return "WEAKENING"
    return "FLAT"


def _relative_momentum(ratios: Sequence[float]) -> str:
    if len(ratios) < 5:
        return "UNKNOWN"
    tail = ratios[-5:]
    if tail[-1] > tail[0] * 1.005:
        return "UP"
    if tail[-1] < tail[0] * 0.995:
        return "DOWN"
    return "FLAT"


def _known_range_position(ratio: float, low: float, high: float) -> Optional[float]:
    if high <= low:
        return None
    return max(0.0, min(1.0, (ratio - low) / (high - low)))


def _reject_forbidden_fields(extra: Dict[str, Any]) -> None:
    bad = FORBIDDEN_LIVE_FIELDS.intersection(extra.keys())
    if bad:
        raise LookaheadViolation(
            f"ex-post / future fields forbidden in live snapshot: {sorted(bad)}"
        )


def _empty_snapshot(*, freshness: str, blockers: List[str], reason: str) -> Dict[str, Any]:
    return {
        "capability": CAP_PROPOSED,
        "status": "unknown",
        "as_of": _now_iso(),
        "ratio": None,
        "historical_low": None,
        "historical_high": None,
        "historical_mean": None,
        "historical_percentile": None,
        "cycle_id": None,
        "cycle_low_known": None,
        "cycle_high_known": None,
        "cycle_percentile": None,
        "known_range_position": None,
        "distance_from_low": None,
        "distance_from_high": None,
        "deviation_from_mean": None,
        "relative_trend": "UNKNOWN",
        "relative_momentum": "UNKNOWN",
        "data_quality": "unknown",
        "source": SOURCE_SYNTHETIC_USDT,
        "freshness": freshness,
        "value_zone": "UNKNOWN",
        "blockers": blockers,
        "ratio_semantics": "research_config_not_tradable_ethbtc",
        "evidence": reason,
        # Observatory mirror compat (LEFT 03 / charts — no allocation signal in B.1)
        "zone": "UNKNOWN",
        "signal": "UNKNOWN",
        "metrics": {"current": "—", "percentile": "—", "velocity": "—"},
    }


def build_eth_btc_value_snapshot(
    *,
    btc_klines_by_tf: Optional[Dict[str, List[dict]]] = None,
    eth_klines_by_tf: Optional[Dict[str, List[dict]]] = None,
    market_meta: Optional[dict] = None,
    now_ms: Optional[int] = None,
    **extra_fields: Any,
) -> Dict[str, Any]:
    """Build EthBtcValueSnapshot from aligned USDT-margined closes."""
    _reject_forbidden_fields(extra_fields)

    freshness = (market_meta or {}).get("status", "unknown")
    now_ms = int(now_ms) if now_ms is not None else _now_ms()

    btc_daily = (btc_klines_by_tf or {}).get("1d") or []
    eth_daily = (eth_klines_by_tf or {}).get("1d") or []
    if not btc_daily or not eth_daily:
        return _empty_snapshot(
            freshness=freshness,
            blockers=["VALUE_TRUTH_UNKNOWN", "HTF_DAILY_MISSING"],
            reason="P2-B.1 · daily klines required for ratio series",
        )

    bars = align_eth_btc_ratio_series(btc_daily, eth_daily, now_ms=now_ms)
    if len(bars) < MIN_HISTORY_BARS:
        return _empty_snapshot(
            freshness=freshness,
            blockers=["VALUE_TRUTH_UNKNOWN", "INSUFFICIENT_HISTORY"],
            reason=f"P2-B.1 · need >={MIN_HISTORY_BARS} closed daily ratio bars",
        )

    ratios = [b["ratio"] for b in bars]
    last = bars[-1]
    ratio = last["ratio"]
    as_of_ms = last["time"] + DAY_MS

    hist_low = min(ratios)
    hist_high = max(ratios)
    hist_mean = sum(ratios) / len(ratios)
    hist_pct = _percentile_rank(ratio, ratios)

    c_start, c_end = _cycle_window(ratios)
    cycle_slice = ratios[c_start:c_end]
    cycle_bars = bars[c_start:c_end]
    cycle_low = min(cycle_slice)
    cycle_high = max(cycle_slice)  # KNOWN max only — bars <= as_of by construction
    cycle_id = _ms_to_iso(cycle_bars[cycle_slice.index(cycle_low)]["time"])[:10]

    cycle_pct = _known_range_position(ratio, cycle_low, cycle_high)
    dist_low = (ratio - hist_low) / hist_low if hist_low > 0 else None
    dist_high = (hist_high - ratio) / hist_high if hist_high > 0 else None
    dev_mean = (ratio - hist_mean) / hist_mean if hist_mean > 0 else None

    rel_trend = _relative_trend(ratios)
    rel_mom = _relative_momentum(ratios)
    zone = classify_value_zone(hist_pct)

    blockers: List[str] = []
    if freshness in ("unknown", "stale"):
        blockers.append("MARKET_DATA_STALE")
    if zone == "UNKNOWN":
        blockers.append("VALUE_TRUTH_UNKNOWN")

    data_quality = "ok" if freshness == "ok" else freshness

    return {
        "capability": CAP_PARTIAL,
        "status": "ok",
        "as_of": _ms_to_iso(as_of_ms),
        "ratio": ratio,
        "historical_low": hist_low,
        "historical_high": hist_high,
        "historical_mean": hist_mean,
        "historical_percentile": hist_pct,
        "cycle_id": cycle_id,
        "cycle_low_known": cycle_low,
        "cycle_high_known": cycle_high,
        "cycle_percentile": cycle_pct,
        "known_range_position": cycle_pct,
        "distance_from_low": dist_low,
        "distance_from_high": dist_high,
        "deviation_from_mean": dev_mean,
        "relative_trend": rel_trend,
        "relative_momentum": rel_mom,
        "data_quality": data_quality,
        "source": SOURCE_SYNTHETIC_USDT,
        "freshness": freshness,
        "value_zone": zone,
        "blockers": blockers,
        "ratio_semantics": "research_config_not_tradable_ethbtc",
        "evidence": "P2-B.1 · SYNTHETIC_USDT_RATIO · known-range only",
        "zone": zone.replace("_", " "),
        "signal": "UNKNOWN",
        "metrics": {
            "current": f"{ratio:.6f}",
            "percentile": f"{hist_pct * 100:.1f}%" if hist_pct is not None else "—",
            "velocity": rel_mom,
        },
    }


def compute_ex_post_cycle_progress(
    *,
    ratio_series: Sequence[float],
    final_cycle_high: float,
) -> Dict[str, Any]:
    """RESEARCH / REVIEW ONLY — must never appear in live observatory snapshots."""
    if not ratio_series or final_cycle_high <= 0:
        return {"ex_post_cycle_progress": None, "warning": "insufficient data"}
    low = min(ratio_series)
    if final_cycle_high <= low:
        return {"ex_post_cycle_progress": None, "warning": "invalid final high"}
    current = ratio_series[-1]
    progress = (current - low) / (final_cycle_high - low)
    return {
        "ex_post_cycle_progress": max(0.0, min(1.0, progress)),
        "cycle_high_final": final_cycle_high,
        "warning": "EX_POST_ONLY · not for live decision",
    }
