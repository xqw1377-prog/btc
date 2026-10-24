"""Frozen C1–C10 contract inputs for P2-C.0 event intelligence harness.

CONTRACT FIXTURE — do not change semantics to make future code pass.
"""
from __future__ import annotations

from typing import Any, Dict

POLICY = "p2-c0-v1"


def _record(**kw: Any) -> Dict[str, Any]:
    base = {
        "event_id": "evt-default",
        "event_class": "MACRO",
        "title": "Test event",
        "factual_claim": "—",
        "published_at": "2026-09-10T12:00:00Z",
        "first_seen_at": "2026-09-10T12:01:00Z",
        "observed_at": "2026-09-10T12:05:00Z",
        "sources": [{"source_id": "src-1", "cluster_id": "cluster-1"}],
        "primary_source": "src-1",
        "evidence_cluster_id": "cluster-1",
        "retracted": False,
        "freshness": "ok",
        "source_quality": "OFFICIAL",
        "policy_stage": "CONFIRMED",
        "revision": 1,
    }
    base.update(kw)
    return base


def _assess(**kw: Any) -> Dict[str, Any]:
    base = {
        "direction_btc": "POSITIVE",
        "direction_eth": "NEUTRAL",
        "impact_btc": 3,
        "impact_eth": 0,
        "priced_in": "PARTIAL",
        "surprise": "BELOW_EXPECTED",
        "transmission_clear": True,
        "market_support": True,
    }
    base.update(kw)
    return base


def _case(case_id: str, **overrides: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "case_id": case_id,
        "policy_hash": POLICY,
        "event_record": _record(),
        "assessment": _assess(),
        "trend": {"btc": {"level": "L4/5"}, "eth": {"level": "L3/5"}},
        "previous_context": {},
        "corroboration": {},
    }
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            merged = dict(base[k])
            merged.update(v)
            base[k] = merged
        else:
            base[k] = v
    return base


# C1 — unverified rumor
C1_UNVERIFIED_RUMOR = _case(
    "C1",
    event_record=_record(
        event_id="evt-c1",
        source_quality="UNVERIFIED",
        policy_stage="RUMOR",
    ),
    assessment=_assess(
        direction_btc="UNKNOWN",
        direction_eth="UNKNOWN",
        transmission_clear=False,
        market_support=False,
    ),
)

# C2 — official fact, direction unclear
C2_OFFICIAL_NO_DIRECTION = _case(
    "C2",
    event_record=_record(
        event_id="evt-c2",
        source_quality="OFFICIAL",
        title="CPI release scheduled",
    ),
    assessment=_assess(
        direction_btc="UNKNOWN",
        direction_eth="UNKNOWN",
        transmission_clear=False,
        market_support=False,
    ),
)

# C3 — E3 but priced in MOST
C3_PRICED_IN_MOST = _case(
    "C3",
    event_record=_record(event_id="evt-c3"),
    assessment=_assess(evidence_grade="E3", priced_in="MOST"),
)

# C4 — E3 + L4 + PARTIAL + fresh
C4_ELIGIBLE_BOOST = _case(
    "C4",
    event_record=_record(event_id="evt-c4", freshness="ok"),
    assessment=_assess(evidence_grade="E3", priced_in="PARTIAL"),
    trend={"btc": {"level": "L4/5"}, "eth": {"level": "L3/5"}},
)

# C5 — E3 + BTC L1
C5_E3_TREND_L1 = _case(
    "C5",
    event_record=_record(event_id="evt-c5"),
    assessment=_assess(evidence_grade="E3", priced_in="PARTIAL"),
    trend={"btc": {"level": "L1/5"}, "eth": {"level": "L2/5"}},
)

# C6 — UNKNOWN event class
C6_UNKNOWN_CLASS = _case(
    "C6",
    event_record=_record(event_id="evt-c6", event_class="UNKNOWN"),
    assessment=_assess(evidence_grade="E3"),
)

# C7 — RETRACTED
C7_RETRACTED = _case(
    "C7",
    event_record=_record(event_id="evt-c7", retracted=True),
    assessment=_assess(evidence_grade="E3"),
    previous_context={
        "event_id": "evt-c7",
        "action_state": "ELIGIBLE",
        "boost_eligibility": "EVENT_BOOST_ELIGIBLE",
    },
)

# C8 — idempotent repeat
C8_IDEMPOTENT = _case(
    "C8",
    event_record=_record(event_id="evt-c8"),
    assessment=_assess(evidence_grade="E3", priced_in="PARTIAL"),
    previous_context={"event_id": "evt-c8", "boost_eligibility": "EVENT_BOOST_ELIGIBLE"},
)

# C9 — 100 reposts, one cluster
C9_SINGLE_CLUSTER = _case(
    "C9",
    event_record=_record(
        event_id="evt-c9",
        evidence_cluster_id="cluster-x",
        sources=[{"source_id": f"repost-{i}", "cluster_id": "cluster-x"} for i in range(100)],
    ),
    corroboration={"unique_cluster_count": 1},
)

# C10 — lookahead injection (top-level forbidden field added in test)

ALL_C_CASES = [
    C1_UNVERIFIED_RUMOR,
    C2_OFFICIAL_NO_DIRECTION,
    C3_PRICED_IN_MOST,
    C4_ELIGIBLE_BOOST,
    C5_E3_TREND_L1,
    C6_UNKNOWN_CLASS,
    C7_RETRACTED,
    C8_IDEMPOTENT,
    C9_SINGLE_CLUSTER,
]
