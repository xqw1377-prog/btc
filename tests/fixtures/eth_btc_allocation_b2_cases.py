"""Frozen B1–B9 contract inputs for P2-B.2 allocation FSM.

CONTRACT FIXTURE — do not change semantics to make future code pass.
"""
from __future__ import annotations

from typing import Any, Dict

POLICY = "p2-b2-v1"


def _value(**kw: Any) -> Dict[str, Any]:
    base = {
        "as_of": "2026-09-10T00:00:00Z",
        "ratio": 0.034,
        "value_zone": "FAIR",
        "relative_trend": "FLAT",
        "freshness": "ok",
        "data_quality": "ok",
        "blockers": [],
    }
    base.update(kw)
    return base


def _trend(level: str, **kw: Any) -> Dict[str, Any]:
    base = {"trend_level": level, "trend_level_num": int(level[1])}
    base.update(kw)
    return base


def _case(case_id: str, **overrides: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "case_id": case_id,
        "policy_hash": POLICY,
        "value": _value(),
        "btc_trend": _trend("L3/5"),
        "eth_trend": _trend("L2/5"),
        "relative_strength": {"eth_vs_btc": "NEUTRAL", "label": "BTC ≈ ETH"},
        "relative_strength_trend": "FLAT",
        "previous_state": {
            "state": "BTC_DEFAULT",
            "allocation_signal": "HOLD_BTC",
        },
        "has_eth_allocation": False,
        "thesis_invalidated": False,
        "authoritative_truth": True,
        "rearm_state": {"disarmed": False},
    }
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            merged = dict(base[k])
            merged.update(v)
            base[k] = merged
        else:
            base[k] = v
    return base


B1_ETH_CHEAP_L1 = _case(
    "B1",
    value=_value(value_zone="CHEAP_ETH", relative_trend="FLAT"),
    eth_trend=_trend("L1/5"),
    previous_state={"state": "BTC_DEFAULT", "allocation_signal": "HOLD_BTC"},
)

B2_ETH_CHEAP_L3_IMPROVING = _case(
    "B2",
    value=_value(value_zone="CHEAP_ETH", relative_trend="IMPROVING"),
    eth_trend=_trend("L3/5"),
    relative_strength={"eth_vs_btc": "STRONGER"},
    relative_strength_trend="IMPROVING",
    previous_state={"state": "ETH_CANDIDATE", "allocation_signal": "WATCH_ETH"},
)

B3_ETH_WEAKENING = _case(
    "B3",
    value=_value(value_zone="FAIR", relative_trend="WEAKENING"),
    eth_trend=_trend("L3/5"),
    relative_strength={"eth_vs_btc": "WEAKER"},
    relative_strength_trend="WEAKENING",
    has_eth_allocation=True,
    previous_state={"state": "ETH_HOLD", "allocation_signal": "HOLD_ETH"},
)

B4_THESIS_INVALIDATED = _case(
    "B4",
    value=_value(value_zone="EXPENSIVE_ETH", relative_trend="WEAKENING"),
    eth_trend=_trend("L2/5"),
    has_eth_allocation=True,
    thesis_invalidated=True,
    previous_state={"state": "ETH_WEAKENING", "allocation_signal": "REDUCE_ETH_ELIGIBLE"},
)

B5_VALUE_UNKNOWN = _case(
    "B5",
    value={
        "as_of": "2026-09-10T00:00:00Z",
        "ratio": None,
        "value_zone": "UNKNOWN",
        "blockers": ["VALUE_TRUTH_UNKNOWN"],
        "freshness": "unknown",
    },
    has_eth_allocation=True,
    previous_state={"state": "ETH_HOLD", "allocation_signal": "HOLD_ETH"},
)

B6_VALUE_STALE = _case(
    "B6",
    value=_value(value_zone="CHEAP_ETH", relative_trend="IMPROVING", freshness="stale", data_quality="stale"),
    eth_trend=_trend("L4/5"),
    relative_strength={"eth_vs_btc": "STRONGER"},
    relative_strength_trend="IMPROVING",
    has_eth_allocation=True,
    previous_state={"state": "ETH_HOLD", "allocation_signal": "HOLD_ETH"},
)

B7_SAME_EVIDENCE = _case(
    "B7",
    value=_value(value_zone="CHEAP_ETH", relative_trend="IMPROVING"),
    eth_trend=_trend("L4/5"),
    relative_strength={"eth_vs_btc": "STRONGER"},
    relative_strength_trend="IMPROVING",
    previous_state={
        "state": "ETH_CONFIRMED",
        "allocation_signal": "INCREASE_ETH_ELIGIBLE",
        "state_transition_key": "PLACEHOLDER",
    },
)

B8_LOOKAHEAD_FIELD = _case(
    "B8",
    value=_value(value_zone="CHEAP_ETH", ex_post_cycle_progress=0.72),
)

B9_INCREASE_NO_TARGET = _case(
    "B9",
    value=_value(value_zone="CHEAP_ETH", relative_trend="IMPROVING"),
    eth_trend=_trend("L4/5"),
    relative_strength={"eth_vs_btc": "STRONGER"},
    relative_strength_trend="IMPROVING",
    previous_state={"state": "ETH_CANDIDATE", "allocation_signal": "WATCH_ETH"},
)

ALL_B_CASES = [
    B1_ETH_CHEAP_L1,
    B2_ETH_CHEAP_L3_IMPROVING,
    B3_ETH_WEAKENING,
    B4_THESIS_INVALIDATED,
    B5_VALUE_UNKNOWN,
    B6_VALUE_STALE,
    B7_SAME_EVIDENCE,
    B8_LOOKAHEAD_FIELD,
    B9_INCREASE_NO_TARGET,
]
