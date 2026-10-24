"""P2-A.2 Funding Truth — read-only cost/crowding fact for OPEN eligibility.

Funding does NOT alter trend level (L0–L5). It only gates OPEN / ADD risk.
CLOSE / REDUCE are never blocked by funding state.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from aurora.risk_kernel import RiskLimits

# PROVISIONAL_E3_PARAM — mechanism frozen; numeric bands not Alpha claims
_FUNDING_ELEVATED_CANDIDATE = 0.0005   # 0.05% per 8h print — E3 to validate band
_FUNDING_EXTREME_CANDIDATE = RiskLimits().max_funding_rate_pct  # aligns with E1 veto


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ms_to_iso(ms: Optional[int]) -> Optional[str]:
    if ms is None:
        return None
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    except (TypeError, ValueError, OSError):
        return None


def fetch_funding_snapshot(
    client: Any,
    symbol: str,
    *,
    market_freshness: str = "ok",
    source: str = "EXCHANGE_READONLY",
) -> Dict[str, Any]:
    """Read funding truth from exchange. rate=null when unknown — never 0 as fake known."""
    base: Dict[str, Any] = {
        "symbol": symbol,
        "funding_rate": None,
        "funding_observed_at": None,
        "funding_next_settlement_at": None,
        "funding_source": source,
        "funding_freshness": "unknown",
        "funding_state": "UNKNOWN",
    }
    if market_freshness == "stale":
        out = dict(base)
        out["funding_freshness"] = "stale"
        out["funding_state"] = "UNKNOWN"
        return out
    if client is None or market_freshness == "unknown":
        return base

    row: Optional[dict] = None
    try:
        if hasattr(client, "futures_mark_price"):
            row = client.futures_mark_price(symbol=symbol)
        elif hasattr(client, "futures_funding_rate"):
            hist = client.futures_funding_rate(symbol=symbol, limit=1)
            if isinstance(hist, list) and hist:
                row = hist[0]
            elif isinstance(hist, dict):
                row = hist
    except Exception:
        return base

    if not isinstance(row, dict):
        return base

    raw_rate = row.get("lastFundingRate")
    if raw_rate is None:
        raw_rate = row.get("fundingRate")

    if raw_rate is None:
        return base

    try:
        rate = float(raw_rate)
    except (TypeError, ValueError):
        return base

    observed_ms = row.get("time") or row.get("updateTime")
    next_ms = row.get("nextFundingTime")

    freshness = "ok" if market_freshness == "ok" else market_freshness
    state = classify_funding_state(rate)

    return {
        "symbol": symbol,
        "funding_rate": rate,
        "funding_observed_at": _ms_to_iso(observed_ms) or _now_iso(),
        "funding_next_settlement_at": _ms_to_iso(next_ms),
        "funding_source": source,
        "funding_freshness": freshness,
        "funding_state": state,
    }


def classify_funding_state(rate: Optional[float]) -> str:
    """Map rate → state. Thresholds are PROVISIONAL candidates."""
    if rate is None:
        return "UNKNOWN"
    abs_rate = abs(rate)
    if abs_rate >= _FUNDING_EXTREME_CANDIDATE:
        return "EXTREME"
    if abs_rate >= _FUNDING_ELEVATED_CANDIDATE:
        return "ELEVATED"
    return "NORMAL"


def apply_funding_open_eligibility(
    trend_action: str,
    funding: Dict[str, Any],
    existing_blockers: Optional[List[str]] = None,
) -> Tuple[str, List[str]]:
    """Merge HTF trend candidate with funding veto. Does not change trend level.

    Returns (action_eligibility, blockers) where eligibility is one of:
    ELIGIBLE | WATCH | HOLD | BLOCK_NEW_RISK
    """
    blockers = list(existing_blockers or [])
    ff = funding.get("funding_freshness", "unknown")
    fs = funding.get("funding_state", "UNKNOWN")

    if ff in ("unknown", "stale") or fs == "UNKNOWN":
        blockers.append("BLOCKED_BY_FUNDING: funding unknown or stale")
        return "BLOCK_NEW_RISK", blockers

    if fs == "EXTREME":
        blockers.append("BLOCKED_BY_FUNDING: funding EXTREME")
        return "BLOCK_NEW_RISK", blockers

    if fs == "ELEVATED" and trend_action == "LONG_ELIGIBLE":
        blockers.append("ELEVATED funding — new long overlay withheld")
        return "WATCH", blockers

    if trend_action == "LONG_ELIGIBLE":
        return "ELIGIBLE", blockers
    if trend_action == "WATCH":
        return "WATCH", blockers
    if trend_action == "HOLD":
        return "HOLD", blockers
    if trend_action == "BLOCKED":
        return "BLOCK_NEW_RISK", blockers
    return "BLOCK_NEW_RISK", blockers
