"""P2-B.2 ETH/BTC Allocation State Machine — contract FSM only.

NOT execution. NOT target weights. NOT orders.
Combines P2-B.1 value truth + P2-A trend truth → allocation eligibility.

FROZEN:
  VALUE_ZONE != ALLOCATION_TRIGGER (cheap ≠ buy)
  UNKNOWN ≠ BTC_RETURN
  ELIGIBLE ≠ spot target %
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, FrozenSet, List, Optional, Set

from aurora.eth_btc_value_truth import FORBIDDEN_LIVE_FIELDS, LookaheadViolation

HARNESS_KIND = "ALLOCATION_FSM_CONTRACT_ONLY"
POLICY_HASH_DEFAULT = "p2-b2-v1"

STATES = (
    "BTC_DEFAULT",
    "ETH_CANDIDATE",
    "ETH_CONFIRMED",
    "ETH_HOLD",
    "ETH_WEAKENING",
    "BTC_RETURN",
)

SIGNALS = (
    "HOLD_BTC",
    "WATCH_ETH",
    "INCREASE_ETH_ELIGIBLE",
    "HOLD_ETH",
    "REDUCE_ETH_ELIGIBLE",
    "RETURN_BTC_ELIGIBLE",
    "NO_REALLOCATION",
)

ELIGIBILITY_SIGNALS = frozenset({
    "INCREASE_ETH_ELIGIBLE",
    "REDUCE_ETH_ELIGIBLE",
    "RETURN_BTC_ELIGIBLE",
})

FORBIDDEN_OUTPUT_KEYS: FrozenSet[str] = frozenset({
    "target_weight",
    "target_pct",
    "target_portfolio",
    "spot_btc",
    "spot_eth",
    "spot_usdt",
    "order_id",
    "client_order_id",
    "exchange_qty",
    "submit",
    "execute",
    "order",
    "execution",
})

ADJACENCY: Dict[str, Set[str]] = {
    "BTC_DEFAULT": {"BTC_DEFAULT", "ETH_CANDIDATE"},
    "ETH_CANDIDATE": {"ETH_CANDIDATE", "ETH_CONFIRMED", "BTC_DEFAULT"},
    "ETH_CONFIRMED": {"ETH_CONFIRMED", "ETH_HOLD", "ETH_WEAKENING"},
    "ETH_HOLD": {"ETH_HOLD", "ETH_WEAKENING"},
    "ETH_WEAKENING": {"ETH_WEAKENING", "ETH_HOLD", "BTC_RETURN"},
    "BTC_RETURN": {"BTC_RETURN", "BTC_DEFAULT"},
}

STATE_SIGNAL = {
    "BTC_DEFAULT": "HOLD_BTC",
    "ETH_CANDIDATE": "WATCH_ETH",
    "ETH_CONFIRMED": "INCREASE_ETH_ELIGIBLE",
    "ETH_HOLD": "HOLD_ETH",
    "ETH_WEAKENING": "REDUCE_ETH_ELIGIBLE",
    "BTC_RETURN": "RETURN_BTC_ELIGIBLE",
}

CHEAP_ZONES = frozenset({
    "DEEP_CHEAP_ETH",
    "CHEAP_ETH",
    "DEEP CHEAP ETH",
    "CHEAP ETH",
})

EXPENSIVE_ZONES = frozenset({
    "EXPENSIVE_ETH",
    "EXTREME_EXPENSIVE_ETH",
    "EXPENSIVE ETH",
    "EXTREME EXPENSIVE ETH",
})

ETH_CONFIRM_LEVEL = 3  # PROVISIONAL_E3_PARAM — L3+ for confirmation


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _level_num(level: Optional[str]) -> int:
    if not level:
        return 0
    for ch in str(level):
        if ch.isdigit():
            return int(ch)
    return 0


def _reject_forbidden_value_fields(value: Dict[str, Any]) -> None:
    bad = FORBIDDEN_LIVE_FIELDS.intersection(value.keys())
    if bad:
        raise LookaheadViolation(
            f"LOOKAHEAD_REJECTED: forbidden value fields {sorted(bad)}"
        )


def _reject_forbidden_output(out: Dict[str, Any]) -> None:
    for key in FORBIDDEN_OUTPUT_KEYS:
        if key in out:
            raise ValueError(f"forbidden output field: {key}")


def compute_state_transition_key(
    value: Dict[str, Any],
    btc_trend: Dict[str, Any],
    eth_trend: Dict[str, Any],
    *,
    policy_hash: str = POLICY_HASH_DEFAULT,
) -> str:
    payload = {
        "value_as_of": value.get("as_of"),
        "ratio": value.get("ratio"),
        "value_zone": value.get("value_zone"),
        "btc_level": btc_trend.get("trend_level") or btc_trend.get("level"),
        "eth_level": eth_trend.get("trend_level") or eth_trend.get("level"),
        "policy_hash": policy_hash,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]
    return f"{digest}"


def _value_unknown(value: Dict[str, Any]) -> bool:
    if value.get("ratio") is None:
        return True
    if value.get("value_zone") in (None, "UNKNOWN"):
        return True
    blockers = value.get("blockers") or []
    return "VALUE_TRUTH_UNKNOWN" in blockers


def _value_stale(value: Dict[str, Any]) -> bool:
    return value.get("freshness") == "stale" or value.get("data_quality") == "stale"


def _is_cheap(zone: Optional[str]) -> bool:
    return zone in CHEAP_ZONES


def _is_expensive(zone: Optional[str]) -> bool:
    return zone in EXPENSIVE_ZONES


def _rs_improving(relative_strength: Dict[str, Any], rs_trend: str) -> bool:
    if rs_trend == "IMPROVING":
        return True
    return relative_strength.get("eth_vs_btc") == "STRONGER"


def _rs_weakening(relative_strength: Dict[str, Any], rs_trend: str) -> bool:
    if rs_trend == "WEAKENING":
        return True
    return relative_strength.get("eth_vs_btc") == "WEAKER"


def _trend_confirmed(eth_trend: Dict[str, Any]) -> bool:
    level = eth_trend.get("trend_level") or eth_trend.get("level")
    return _level_num(level) >= ETH_CONFIRM_LEVEL


def _derive_target_state(inp: Dict[str, Any]) -> str:
    value = inp.get("value") or {}
    eth_trend = inp.get("eth_trend") or {}
    rs = inp.get("relative_strength") or {}
    rs_trend = inp.get("relative_strength_trend", "FLAT")
    prev = (inp.get("previous_state") or {}).get("state", "BTC_DEFAULT")
    has_eth = bool(inp.get("has_eth_allocation"))
    thesis_invalidated = bool(inp.get("thesis_invalidated"))
    authoritative = inp.get("authoritative_truth", True)

    if _value_unknown(value):
        return prev if prev else "BTC_DEFAULT"

    if thesis_invalidated and authoritative:
        return "BTC_RETURN"

    zone = value.get("value_zone")
    rel_trend = value.get("relative_trend", "UNKNOWN")

    if has_eth and _rs_weakening(rs, rs_trend):
        if prev in ("ETH_HOLD", "ETH_CONFIRMED", "ETH_WEAKENING"):
            return "ETH_WEAKENING"

    if has_eth and prev in ("ETH_CONFIRMED", "ETH_HOLD", "ETH_WEAKENING"):
        if _is_expensive(zone) or thesis_invalidated:
            return "BTC_RETURN" if thesis_invalidated else "ETH_WEAKENING"
        if _is_cheap(zone) or zone == "FAIR":
            if _trend_confirmed(eth_trend) and rel_trend != "WEAKENING":
                return "ETH_HOLD"
        return prev

    if (
        _is_cheap(zone)
        and _trend_confirmed(eth_trend)
        and rel_trend == "IMPROVING"
        and _rs_improving(rs, rs_trend)
    ):
        return "ETH_CONFIRMED"

    if _is_cheap(zone):
        rearm = inp.get("rearm_state") or {}
        if prev == "BTC_RETURN" and rearm.get("disarmed"):
            return "BTC_RETURN"
        return "ETH_CANDIDATE"

    if has_eth and prev in ("ETH_HOLD", "ETH_WEAKENING"):
        return "ETH_WEAKENING" if _rs_weakening(rs, rs_trend) else "ETH_HOLD"

    return "BTC_DEFAULT"


def _apply_adjacency(
    prev_state: str,
    target: str,
    *,
    thesis_invalidated: bool,
) -> str:
    if prev_state not in ADJACENCY:
        prev_state = "BTC_DEFAULT"
    allowed = ADJACENCY[prev_state]

    if target in allowed:
        return target

    # ETH_CANDIDATE → BTC_RETURN only with explicit thesis invalidation
    if prev_state == "ETH_CANDIDATE" and target == "BTC_RETURN":
        return "BTC_RETURN" if thesis_invalidated else prev_state

    # Never BTC_DEFAULT → BTC_RETURN
    if prev_state == "BTC_DEFAULT" and target == "BTC_RETURN":
        return "BTC_DEFAULT"

    # Multi-hop: step one neighbor toward target if possible
    if prev_state == "BTC_DEFAULT" and target == "ETH_CONFIRMED":
        return "ETH_CANDIDATE"
    if prev_state == "ETH_CANDIDATE" and target == "ETH_HOLD":
        return "ETH_CONFIRMED"
    if prev_state == "ETH_CONFIRMED" and target == "BTC_RETURN":
        return "ETH_WEAKENING"

    return prev_state


def evaluate_allocation_fsm(inp: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate six-state allocation FSM from dict inputs (contract harness)."""
    value = dict(inp.get("value") or {})
    btc_trend = dict(inp.get("btc_trend") or {})
    eth_trend = dict(inp.get("eth_trend") or {})
    rs = dict(inp.get("relative_strength") or {})
    previous = dict(inp.get("previous_state") or {})
    policy_hash = str(inp.get("policy_hash") or POLICY_HASH_DEFAULT)

    _reject_forbidden_value_fields(value)

    prev_state = previous.get("state", "BTC_DEFAULT")
    prev_signal = previous.get("allocation_signal", STATE_SIGNAL.get(prev_state, "HOLD_BTC"))
    transition_key = compute_state_transition_key(
        value, btc_trend, eth_trend, policy_hash=policy_hash,
    )

    reasons: List[str] = []
    blockers: List[str] = list(inp.get("blockers") or [])

    idempotent = (
        previous.get("state_transition_key") == transition_key
        and previous.get("state_transition_key") is not None
    )

    if _value_unknown(value):
        blockers.append("VALUE_TRUTH_UNKNOWN")
        reasons.append("value truth unknown — NO REALLOCATION")
        out_state = prev_state if prev_state else "BTC_DEFAULT"
        signal = "NO_REALLOCATION"
        if out_state == "BTC_RETURN":
            out_state = "BTC_DEFAULT"
            reasons.append("UNKNOWN cannot authorize BTC_RETURN")
        rearm = dict(previous.get("rearm_state") or {"disarmed": False})
        out = _build_output(
            inp, out_state, signal, value, btc_trend, eth_trend, rs,
            reasons, blockers, transition_key, rearm, idempotent=True,
        )
        _reject_forbidden_output(out)
        return out

    stale = _value_stale(value)
    if stale:
        blockers.append("BLOCK_NEW_REALLOCATION")
        reasons.append("value truth stale — block new reallocation")

    target = _derive_target_state(inp)
    thesis_invalidated = bool(inp.get("thesis_invalidated"))

    if stale:
        if target in ("ETH_CANDIDATE", "ETH_CONFIRMED") and prev_state in (
            "BTC_DEFAULT", "ETH_CANDIDATE",
        ):
            target = prev_state
            reasons.append("stale — cannot advance into candidate/confirmed")
        if target == "ETH_CONFIRMED":
            target = prev_state

    out_state = _apply_adjacency(
        prev_state, target, thesis_invalidated=thesis_invalidated,
    )

    if idempotent:
        blockers.append("IDEMPOTENT_EVIDENCE")
        reasons.append("same evidence epoch — no state re-advance")
        out_state = prev_state
        if prev_signal in ELIGIBILITY_SIGNALS:
            signal = "NO_REALLOCATION"
            reasons.append("no duplicate eligibility")
        else:
            signal = prev_signal
    else:
        signal = STATE_SIGNAL.get(out_state, "NO_REALLOCATION")
        if stale and signal == "INCREASE_ETH_ELIGIBLE":
            signal = "NO_REALLOCATION"
            out_state = prev_state
            reasons.append("stale — increase not eligible")

    rearm = _update_rearm(previous.get("rearm_state"), out_state, transition_key)

    out = _build_output(
        inp, out_state, signal, value, btc_trend, eth_trend, rs,
        reasons, blockers, transition_key, rearm, idempotent=idempotent,
    )
    _reject_forbidden_output(out)
    return out


def _update_rearm(
    prev_rearm: Optional[Dict[str, Any]],
    state: str,
    epoch: str,
) -> Dict[str, Any]:
    rearm = dict(prev_rearm or {"disarmed": False, "last_return_epoch": None})
    if state == "BTC_RETURN":
        rearm["disarmed"] = True
        rearm["last_return_epoch"] = epoch
    elif state == "BTC_DEFAULT" and rearm.get("disarmed"):
        rearm["disarmed"] = False
        rearm["rearm_epoch"] = epoch
    return rearm


def _build_output(
    inp: Dict[str, Any],
    state: str,
    signal: str,
    value: Dict[str, Any],
    btc_trend: Dict[str, Any],
    eth_trend: Dict[str, Any],
    rs: Dict[str, Any],
    reasons: List[str],
    blockers: List[str],
    transition_key: str,
    rearm: Dict[str, Any],
    *,
    idempotent: bool,
) -> Dict[str, Any]:
    return {
        "harness_kind": HARNESS_KIND,
        "case_id": inp.get("case_id", "UNKNOWN"),
        "as_of": value.get("as_of") or _now_iso(),
        "state": state,
        "allocation_signal": signal,
        "value_zone": value.get("value_zone"),
        "eth_trend_level": eth_trend.get("trend_level") or eth_trend.get("level"),
        "btc_trend_level": btc_trend.get("trend_level") or btc_trend.get("level"),
        "relative_strength": rs.get("eth_vs_btc") or rs.get("label", "UNKNOWN"),
        "relative_trend": value.get("relative_trend", "UNKNOWN"),
        "reasons": reasons,
        "blockers": blockers,
        "evidence_epoch": transition_key,
        "state_transition_key": transition_key,
        "rearm_state": rearm,
        "idempotent": idempotent,
        "policy_hash": inp.get("policy_hash") or POLICY_HASH_DEFAULT,
    }
