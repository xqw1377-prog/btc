"""P2-C.0 Event Intelligence CONTRACT HARNESS — offline reference only.

NOT live news feed. NOT P3 runtime. NOT execution.

Answers three separated questions:
  A. What happened?        → EventRecord summary
  B. What might it mean?   → EventAssessment
  C. Risk-budget eligible? → EventActionEligibility / EventContextCandidate

FROZEN:
  Evidence Grade ≠ Action Eligibility
  E3 ≠ ELIGIBLE (without trend / priced_in / freshness gates)
  ACTIVE = UNREACHABLE_BY_POLICY (EXECUTION DENIED · P3 HOLD)
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

HARNESS_KIND = "EVENT_CONTRACT_HARNESS_ONLY"
POLICY_HASH_DEFAULT = "p2-c0-v1"
ACTIVE_UNREACHABLE = "UNREACHABLE_BY_POLICY"

FORBIDDEN_LIVE_FIELDS = frozenset({
    "ex_post_revision",
    "revised_actual_value",
    "future_surprise",
    "lookahead_knowledge",
})

FORBIDDEN_OUTPUT_KEYS: Set[str] = frozenset({
    "target_leverage",
    "target_weight",
    "target_portfolio",
    "order_qty",
    "exchange_qty",
    "buy",
    "sell",
    "submit",
    "execute",
    "open_short",
    "order_id",
    "client_order_id",
})

EVIDENCE_GRADES = ("E0", "E1", "E2", "E3")
ACTION_STATES = ("NONE", "WATCH", "CONFIRMED", "ELIGIBLE", "RISK_OFF")
BOOST_ELIGIBILITY = (
    "NONE",
    "WATCH_ONLY",
    "CONFIRMED_FACT",
    "EVENT_BOOST_ELIGIBLE",
    "RISK_OFF_ELIGIBLE",
    "NO_BOOST",
)


class LookaheadViolation(ValueError):
    """C10 — future knowledge injected at decision_time."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _level_num(level: Optional[str]) -> int:
    if not level:
        return 0
    for ch in str(level):
        if ch.isdigit():
            return int(ch)
    return 0


def _reject_forbidden_input(extra: Dict[str, Any]) -> None:
    bad = FORBIDDEN_LIVE_FIELDS.intersection(extra.keys())
    if bad:
        raise LookaheadViolation(
            f"LOOKAHEAD_REJECTED: forbidden fields {sorted(bad)}"
        )


def _reject_forbidden_output(out: Dict[str, Any]) -> None:
    for key in FORBIDDEN_OUTPUT_KEYS:
        if key in out:
            raise ValueError(f"forbidden output field: {key}")


def compute_evidence_version(record: Dict[str, Any], assessment: Dict[str, Any]) -> str:
    payload = {
        "event_id": record.get("event_id"),
        "revision": record.get("revision"),
        "retracted": record.get("retracted"),
        "published_at": record.get("published_at"),
        "direction_btc": assessment.get("direction_btc"),
        "priced_in": assessment.get("priced_in"),
        "evidence_grade_override": assessment.get("evidence_grade"),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]
    return digest


def _corroboration_count(record: Dict[str, Any], corroboration: Dict[str, Any]) -> int:
    if corroboration.get("unique_cluster_count") is not None:
        return int(corroboration["unique_cluster_count"])
    sources = record.get("sources") or []
    clusters = {record.get("evidence_cluster_id") or s.get("cluster_id") for s in sources}
    clusters.discard(None)
    if clusters:
        return len(clusters)
    return max(1, len(sources)) if sources else 0


def _derive_evidence_grade(
    record: Dict[str, Any],
    assessment: Dict[str, Any],
) -> str:
    if assessment.get("evidence_grade") in EVIDENCE_GRADES:
        return assessment["evidence_grade"]
    if record.get("retracted"):
        return "E0"
    quality = (record.get("source_quality") or "").upper()
    if quality in ("UNVERIFIED", "RUMOR", "UNKNOWN"):
        return "E0"
    if (record.get("event_class") or "").upper() == "UNKNOWN":
        return "E0"
    direction_btc = assessment.get("direction_btc", "UNKNOWN")
    direction_eth = assessment.get("direction_eth", "UNKNOWN")
    if direction_btc == "UNKNOWN" and direction_eth == "UNKNOWN":
        if quality in ("OFFICIAL", "PRIMARY") or record.get("policy_stage") == "CONFIRMED":
            return "E1"
        return "E0"
    mechanism = assessment.get("transmission_clear", False)
    market_support = assessment.get("market_support", False)
    if mechanism and market_support:
        return "E3"
    if mechanism or (direction_btc != "UNKNOWN" or direction_eth != "UNKNOWN"):
        return "E2"
    return "E1"


def _derive_action_state_and_boost(
    *,
    grade: str,
    record: Dict[str, Any],
    assessment: Dict[str, Any],
    trend: Dict[str, Any],
) -> Tuple[str, str, List[str], List[str]]:
    reasons: List[str] = []
    blockers: List[str] = []
    event_class = (record.get("event_class") or "").upper()
    priced_in = (assessment.get("priced_in") or "UNKNOWN").upper()
    freshness = (record.get("freshness") or "unknown").lower()
    btc_level = _level_num((trend.get("btc") or {}).get("level"))
    negative = (
        assessment.get("direction_btc") == "NEGATIVE"
        or assessment.get("impact_btc", 0) < 0
        or assessment.get("direction_eth") == "NEGATIVE"
    )

    if record.get("retracted"):
        reasons.append("event RETRACTED — eligibility removed")
        blockers.append("EVENT_RETRACTED")
        return "NONE", "NO_BOOST", reasons, blockers

    if event_class == "UNKNOWN":
        reasons.append("UNKNOWN event class — alert only")
        blockers.append("UNKNOWN_EVENT_CLASS")
        return "WATCH", "WATCH_ONLY", reasons, blockers

    if grade == "E0":
        reasons.append("E0 — unverified or insufficient evidence")
        return "WATCH", "WATCH_ONLY", reasons, blockers

    if grade == "E1":
        reasons.append("E1 — fact confirmed, direction or transmission unclear")
        return "CONFIRMED", "CONFIRMED_FACT", reasons, blockers

    if negative and grade in ("E2", "E3"):
        reasons.append("E3 negative — max RISK_OFF, no short authority")
        blockers.append("NO_SHORT_AUTHORITY")
        return "RISK_OFF", "RISK_OFF_ELIGIBLE", reasons, blockers

    if priced_in == "MOST":
        reasons.append("priced_in MOST — NO BOOST")
        blockers.append("PRICED_IN_MOST")
        return "CONFIRMED", "NO_BOOST", reasons, blockers

    if priced_in == "UNKNOWN":
        reasons.append("priced_in UNKNOWN — cannot auto ELIGIBLE")
        blockers.append("PRICED_IN_UNKNOWN")
        return "CONFIRMED", "NO_BOOST", reasons, blockers

    if grade == "E3" and btc_level < 3:
        reasons.append("E3 but BTC trend below L3 — CONFIRMED only (C5)")
        blockers.append("TREND_NOT_CONFIRMED")
        return "CONFIRMED", "NO_BOOST", reasons, blockers

    if freshness in ("stale", "unknown"):
        reasons.append(f"freshness {freshness} — block boost")
        blockers.append("FRESHNESS_FAIL")
        return "CONFIRMED", "NO_BOOST", reasons, blockers

    if grade == "E3" and btc_level >= 3 and priced_in in ("NONE", "PARTIAL"):
        reasons.append("E3 + trend aligned + priced_in acceptable")
        return "ELIGIBLE", "EVENT_BOOST_ELIGIBLE", reasons, blockers

    if grade == "E2":
        reasons.append("E2 — transmission clear, awaiting full E3 / gates")
        return "CONFIRMED", "NO_BOOST", reasons, blockers

    return "WATCH", "WATCH_ONLY", reasons, blockers


def evaluate_event_contract(inp: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate P2-C.0 event contract from pure dict inputs."""
    extra = {k: v for k, v in inp.items() if k not in (
        "case_id", "event_record", "assessment", "trend",
        "previous_context", "corroboration", "policy_hash",
    )}
    _reject_forbidden_input(extra)

    case_id = inp.get("case_id", "UNKNOWN")
    record = dict(inp.get("event_record") or {})
    assessment = dict(inp.get("assessment") or {})
    trend = dict(inp.get("trend") or {})
    previous = dict(inp.get("previous_context") or {})
    corroboration = dict(inp.get("corroboration") or {})

    evidence_version = compute_evidence_version(record, assessment)
    idempotent = (
        previous.get("evidence_version") == evidence_version
        and previous.get("evidence_version") is not None
        and record.get("event_id") == previous.get("event_id")
    )

    corro_count = _corroboration_count(record, corroboration)
    grade = _derive_evidence_grade(record, assessment)
    action_state, boost_eligibility, reasons, blockers = _derive_action_state_and_boost(
        grade=grade,
        record=record,
        assessment=assessment,
        trend=trend,
    )

    if idempotent:
        blockers.append("IDEMPOTENT_EVIDENCE")
        reasons.append("same event_id + evidence_version — no duplicate boost")
        action_state = previous.get("action_state", action_state)
        boost_eligibility = "NO_BOOST"
        if previous.get("boost_eligibility") == "EVENT_BOOST_ELIGIBLE":
            boost_eligibility = "NO_BOOST"

    # ACTIVE never reachable in P2-C.0
    if action_state == "ACTIVE":
        action_state = "ELIGIBLE"
        blockers.append(ACTIVE_UNREACHABLE)

    event_context = {
        "evidence_grade": grade,
        "direction_btc": assessment.get("direction_btc", "UNKNOWN"),
        "direction_eth": assessment.get("direction_eth", "UNKNOWN"),
        "impact_btc": assessment.get("impact_btc"),
        "impact_eth": assessment.get("impact_eth"),
        "priced_in": assessment.get("priced_in", "UNKNOWN"),
        "expected_window": assessment.get("expected_window"),
        "action_state": action_state,
        "boost_eligibility": boost_eligibility,
        "active_policy": ACTIVE_UNREACHABLE,
        "corroboration_count": corro_count,
        "event_id": record.get("event_id"),
        "evidence_version": evidence_version,
        "reasons": reasons,
        "blockers": blockers,
    }

    out = {
        "harness_kind": HARNESS_KIND,
        "case_id": case_id,
        "as_of": record.get("observed_at") or _now_iso(),
        "event_record_summary": {
            "event_id": record.get("event_id"),
            "event_class": record.get("event_class"),
            "title": record.get("title"),
            "retracted": bool(record.get("retracted")),
            "freshness": record.get("freshness"),
            "source_quality": record.get("source_quality"),
            "evidence_cluster_id": record.get("evidence_cluster_id"),
        },
        "event_assessment": {
            "direction_btc": assessment.get("direction_btc"),
            "direction_eth": assessment.get("direction_eth"),
            "impact_btc": assessment.get("impact_btc"),
            "impact_eth": assessment.get("impact_eth"),
            "priced_in": assessment.get("priced_in"),
            "surprise": assessment.get("surprise"),
        },
        "event_action_eligibility": {
            "action_state": action_state,
            "boost_eligibility": boost_eligibility,
            "active_unreachable": ACTIVE_UNREACHABLE,
        },
        "event_context": event_context,
        "reasons": reasons,
        "blockers": blockers,
        "evidence_version": evidence_version,
        "idempotent": idempotent,
        "policy_hash": inp.get("policy_hash") or POLICY_HASH_DEFAULT,
    }
    _reject_forbidden_output(out)
    return out
