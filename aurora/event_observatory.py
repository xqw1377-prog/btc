"""P2-C.3 Event Observatory projection — C1 truth + C2 eligibility → UI bundle.

NOT live official source ingestion by default.
NOT execution. Frontend must not recompute eligibility.

FROZEN:
  SOURCE_NOT_CONNECTED ≠ NO_EVENT_OBSERVED
  SOURCE_ERROR must not collapse to empty calm UI
  primary_event_id sort = display priority only (RISK_OFF > ELIGIBLE > …)
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from aurora.event_action_eligibility import (
    ACTIVE_UNREACHABLE,
    assess_action_eligibility,
    assess_impact,
    assess_priced_in,
    evaluate_event_eligibility,
    get_event_class_policies,
)
from aurora.event_truth import (
    EventTruthLedger,
    evaluate_source_fetch,
    get_source_registry,
)

CAP_SEMANTICS = "READ-ONLY-SEMANTICS"
INGESTION_NOT_CONNECTED = "NOT_CONNECTED"
INGESTION_CONNECTED = "CONNECTED"

ACTION_PRIORITY = {
    "RISK_OFF": 5,
    "ELIGIBLE": 4,
    "CONFIRMED": 3,
    "WATCH": 2,
    "NONE": 1,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_to_ms(iso: Optional[str]) -> Optional[int]:
    if not iso:
        return None
    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)
    except (TypeError, ValueError, OSError):
        return None


def _impact_line(direction: str, impact: Any) -> str:
    if direction == "UNKNOWN" or impact == "UNKNOWN":
        return "UNKNOWN"
    sign = "+" if isinstance(impact, (int, float)) and impact >= 0 else ""
    return f"{direction} · {sign}{impact}"


def _grade_label(grade: str, action_state: str, retracted: bool) -> str:
    if retracted:
        return f"RETRACTED · was {grade}"
    verified = "VERIFIED" if grade == "E3" else "CONFIRMED"
    return f"{grade} · {verified if grade in ('E2', 'E3') else action_state}"


def _trend_line(btc_trend: Optional[Dict[str, Any]]) -> str:
    if not btc_trend:
        return "UNKNOWN"
    d = btc_trend.get("trend_direction") or btc_trend.get("dir") or "UNKNOWN"
    lvl = btc_trend.get("trend_level") or btc_trend.get("level") or "L0/5"
    return f"{d} · {lvl}"


def _headline_action(eligibility: Dict[str, Any]) -> str:
    boost = eligibility.get("boost_eligibility") or "NO_BOOST"
    action = eligibility.get("action_state") or "WATCH"
    if boost == "EVENT_BOOST_ELIGIBLE":
        return "EVENT BOOST ELIGIBLE"
    if boost == "RISK_OFF_ELIGIBLE":
        return "DEFENSIVE ACTION ELIGIBLE"
    if action == "NONE":
        return "NO ACTIVE EVENT REQUEST"
    if boost in ("NO_BOOST", "CONFIRMED_FACT"):
        return "NO BOOST"
    if boost == "WATCH_ONLY":
        return "WATCH"
    return boost.replace("_", " ")


def _tone_from_item(eligibility: Dict[str, Any], impact: Dict[str, Any]) -> str:
    if eligibility.get("action_state") == "RISK_OFF":
        return "defensive"
    if eligibility.get("boost_eligibility") == "EVENT_BOOST_ELIGIBLE":
        return "positive"
    if impact.get("btc_direction") == "NEGATIVE":
        return "caution"
    return "neutral"


def _why_not(eligibility: Dict[str, Any]) -> Optional[str]:
    blockers = eligibility.get("blockers") or []
    if not blockers:
        return None
    return blockers[0].replace("_", " ")


def _build_right_evidence(
    truth: Dict[str, Any],
    impact: Dict[str, Any],
    priced: Dict[str, Any],
    eligibility: Dict[str, Any],
    *,
    trend_aligned: bool,
) -> Dict[str, Any]:
    return {
        "what_happened": {
            "event_class": truth.get("event_class"),
            "factual_claim": truth.get("factual_claim"),
            "policy_stage": truth.get("stage") or "EVENT_TRUTH",
            "first_observed_at": truth.get("first_observed_at"),
            "latest_revision": truth.get("event_version"),
            "event_time": truth.get("event_time"),
            "source_published_at": truth.get("source_published_at"),
        },
        "evidence": {
            "evidence_grade": impact.get("evidence_grade"),
            "primary_source": truth.get("source_id"),
            "evidence_cluster_id": truth.get("evidence_cluster_id"),
            "independent_clusters": 1,
            "conflicts": truth.get("conflict"),
            "revision_type": truth.get("revision_type"),
            "retracted": bool(truth.get("retracted")),
            "consensus_truth_state": truth.get("consensus_truth_state"),
            "expected_value": truth.get("expected_value"),
            "surprise": truth.get("surprise"),
        },
        "impact": {
            "btc_direction": impact.get("btc_direction"),
            "btc_impact": impact.get("btc_impact"),
            "eth_direction": impact.get("eth_direction"),
            "eth_impact": impact.get("eth_impact"),
            "transmission_path": impact.get("transmission_path") or [],
            "opposing_evidence": impact.get("opposing_evidence") or [],
            "impact_is_not_probability": True,
        },
        "market_response": {
            "anchor_time": priced.get("anchor_time"),
            "priced_in": priced.get("priced_in"),
            "chase_distance": priced.get("chase_distance"),
            "freshness": priced.get("freshness"),
            "trend_alignment": "YES" if trend_aligned else "NO",
            "btc_move_in_vol_units": priced.get("btc_move_in_vol_units"),
            "eth_move_in_vol_units": priced.get("eth_move_in_vol_units"),
        },
        "action_eligibility": {
            "action_state": eligibility.get("action_state"),
            "boost_eligibility": eligibility.get("boost_eligibility"),
            "event_increment_request": eligibility.get("event_increment_request"),
            "active_unreachable": ACTIVE_UNREACHABLE,
            "risk_off_overlays": eligibility.get("risk_off_overlays") or [],
            "reasons": eligibility.get("reasons") or [],
            "blockers": eligibility.get("blockers") or [],
            "eligible_not_active": eligibility.get("eligible_not_active", False),
        },
        "footer": {
            "eligible_not_active": "ELIGIBLE ≠ ACTIVE",
            "read_only": "READ ONLY",
            "no_short": (
                "NO SHORT AUTHORITY"
                if "NO_SHORT_AUTHORITY" in (eligibility.get("blockers") or [])
                else None
            ),
        },
    }


def _project_event_item(
    truth: Dict[str, Any],
    *,
    btc_trend: Optional[Dict[str, Any]] = None,
    eth_trend: Optional[Dict[str, Any]] = None,
    market_context: Optional[Dict[str, Any]] = None,
    market_freshness: str = "ok",
    as_of_ms: Optional[int] = None,
) -> Dict[str, Any]:
    impact = assess_impact(truth, as_of=truth.get("last_observed_at"))
    priced = assess_priced_in(truth, market_context or {}, as_of_ms=as_of_ms)
    eligibility = assess_action_eligibility(
        event_truth=truth,
        event_impact=impact,
        priced_in=priced,
        btc_trend_snapshot=btc_trend or {},
        eth_trend_snapshot=eth_trend or {},
        market_freshness=market_freshness,
    )
    trend_aligned = priced.get("trend_alignment") if priced.get("trend_alignment") else (
        impact.get("btc_direction") == "POSITIVE"
        and _trend_level_num(btc_trend) >= 3
    )
    title = (truth.get("title") or truth.get("event_class") or "EVENT").upper()
    retracted = bool(truth.get("retracted"))

    left = {
        "title": title,
        "grade_label": _grade_label(
            impact.get("evidence_grade", "E0"),
            eligibility.get("action_state", "WATCH"),
            retracted,
        ),
        "btc_impact_line": _impact_line(
            impact.get("btc_direction", "UNKNOWN"),
            impact.get("btc_impact"),
        ),
        "eth_impact_line": _impact_line(
            impact.get("eth_direction", "UNKNOWN"),
            impact.get("eth_impact"),
        ),
        "priced_in": priced.get("priced_in", "UNKNOWN"),
        "trend_line": _trend_line(btc_trend),
        "trend_align": "YES" if trend_aligned else "NO",
        "headline_action": _headline_action(eligibility),
        "why_not": _why_not(eligibility),
        "tone": _tone_from_item(eligibility, impact),
        "retracted": retracted,
        "revision": truth.get("event_version"),
    }

    return {
        "event_id": truth.get("event_key"),
        "event_key": truth.get("event_key"),
        "event_version": truth.get("event_version"),
        "priority": ACTION_PRIORITY.get(eligibility.get("action_state", "WATCH"), 0),
        "freshness_ms": _iso_to_ms(truth.get("first_observed_at")) or 0,
        "left": left,
        "eligibility": {
            "action_state": eligibility.get("action_state"),
            "boost_eligibility": eligibility.get("boost_eligibility"),
            "event_increment_request": eligibility.get("event_increment_request"),
        },
        "impact": impact,
        "priced_in": priced,
        "right": _build_right_evidence(
            truth, impact, priced, eligibility, trend_aligned=bool(trend_aligned),
        ),
    }


def _trend_level_num(trend: Optional[Dict[str, Any]]) -> int:
    if not trend:
        return 0
    lvl = trend.get("trend_level") or trend.get("level") or ""
    for ch in str(lvl):
        if ch.isdigit():
            return int(ch)
    return 0


def _select_primary(items: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not items:
        return None
    return sorted(
        items,
        key=lambda x: (-x.get("priority", 0), -x.get("freshness_ms", 0)),
    )[0]


def _left_card_from_primary(
    primary: Optional[Dict[str, Any]],
    *,
    disconnected: bool = False,
    source_error: bool = False,
    no_event: bool = False,
) -> Dict[str, Any]:
    if disconnected:
        return {
            "index": "04",
            "title": "MAJOR EVENT",
            "subtitle": "重大事件",
            "headlines": ["OFFICIAL EVENT SOURCES", "NOT CONNECTED"],
            "event_state": "UNKNOWN",
            "headline_action": "NO ACTION ELIGIBILITY",
            "meta": ["READ ONLY", "ELIGIBLE ≠ ACTIVE"],
            "evidence": "Official ingestion not connected — cannot infer no events",
            "tone": "unknown",
            "mirror_rows": [],
        }
    if source_error:
        return {
            "index": "04",
            "title": "MAJOR EVENT",
            "subtitle": "重大事件",
            "headlines": ["SOURCE ERROR", "EVENT TRUTH UNKNOWN"],
            "event_state": "UNKNOWN",
            "headline_action": "NO NEW BOOST",
            "meta": ["READ ONLY", "SOURCE_ERROR"],
            "evidence": "Fetch failure ≠ calm market",
            "tone": "unknown",
            "mirror_rows": [],
        }
    if no_event or not primary:
        return {
            "index": "04",
            "title": "MAJOR EVENT",
            "subtitle": "重大事件",
            "headlines": ["SOURCE HEALTH OK", "NO EVENT OBSERVED"],
            "event_state": "OK",
            "headline_action": "NO DECISION EVENTS",
            "meta": ["READ ONLY", "DECISION EVENTS NONE"],
            "evidence": "Connected · no major event in observation window",
            "tone": "neutral",
            "mirror_rows": [],
        }

    left = primary["left"]
    headlines = [left["title"], left["grade_label"]]
    mirror_rows = [
        {"label": "BTC IMPACT", "value": left["btc_impact_line"]},
        {"label": "PRICED-IN", "value": left["priced_in"]},
        {"label": "TREND", "value": left["trend_line"]},
    ]
    if left.get("trend_align") == "YES":
        mirror_rows.append({"label": "TREND ALIGN", "value": "YES"})
    if primary["eligibility"].get("boost_eligibility") == "RISK_OFF_ELIGIBLE":
        mirror_rows = [
            {"label": "BTC IMPACT", "value": left["btc_impact_line"]},
            {"label": "ACTION", "value": "RISK-OFF ELIGIBLE"},
        ]

    meta = ["READ ONLY", "ELIGIBLE ≠ ACTIVE"]
    if primary["eligibility"].get("boost_eligibility") == "EVENT_BOOST_ELIGIBLE":
        meta.append("P3 HOLD")
    if primary["eligibility"].get("boost_eligibility") == "RISK_OFF_ELIGIBLE":
        meta.append("NO SHORT AUTHORITY")

    disclaimer = None
    if left.get("retracted"):
        disclaimer = f"Revision #{left.get('revision')} · Eligibility revoked"
    elif left.get("why_not"):
        disclaimer = f"Why · {left['why_not']}"

    return {
        "index": "04",
        "title": "MAJOR EVENT",
        "subtitle": "重大事件",
        "headlines": headlines,
        "headline_action": left["headline_action"],
        "event_state": "OK",
        "meta": meta,
        "evidence": left.get("why_not") or left["headline_action"],
        "disclaimer": disclaimer,
        "tone": left["tone"],
        "mirror_rows": mirror_rows,
        "retracted": left.get("retracted", False),
    }


def build_event_observatory_snapshot(
    *,
    official_sources_connected: bool = False,
    source_fetch_status: str = "not_connected",
    fixture_pipeline: Optional[List[Dict[str, Any]]] = None,
    btc_trend: Optional[Dict[str, Any]] = None,
    eth_trend: Optional[Dict[str, Any]] = None,
    market_freshness: str = "ok",
    as_of_ms: Optional[int] = None,
    last_success_at_ms: Optional[int] = None,
) -> Dict[str, Any]:
    """Project event semantics for observatory.event bundle."""
    as_of_ms = as_of_ms or int(datetime.now(timezone.utc).timestamp() * 1000)
    registry = get_source_registry()
    sources_health: List[Dict[str, Any]] = []

    if not official_sources_connected:
        for sid in registry:
            sources_health.append(
                evaluate_source_fetch(source_id=sid, fetch_status="not_connected")
            )
        left_card = _left_card_from_primary(None, disconnected=True)
        return {
            "capability": CAP_SEMANTICS,
            "status": "not_connected",
            "as_of": _now_iso(),
            "official_source_ingestion": INGESTION_NOT_CONNECTED,
            "source_registry": list(registry.keys()),
            "sources_health": sources_health,
            "source_health_summary": "SOURCE_NOT_CONNECTED",
            "event_state": "UNKNOWN",
            "observation_state": "SOURCE_NOT_CONNECTED",
            "last_observed_at": None,
            "decision_events": "NONE",
            "primary_event_id": None,
            "active_candidate_count": 0,
            "items": [],
            "left_card": left_card,
            "right_evidence": {
                "status": "not_connected",
                "title": "EVENT INTELLIGENCE",
                "source_health": "SOURCE_NOT_CONNECTED",
                "event_state": "UNKNOWN",
                "message": "OFFICIAL EVENT SOURCES NOT CONNECTED",
                "layers": {},
            },
            "disclaimer": "READ ONLY · OFFICIAL INGESTION NOT CONNECTED",
        }

    # Connected path — evaluate aggregate source health
    fetch = source_fetch_status or "ok"
    for sid in registry:
        sources_health.append(
            evaluate_source_fetch(
                source_id=sid,
                fetch_status=fetch,
                events=[] if fetch == "ok" else None,
                last_success_at_ms=last_success_at_ms,
                now_ms=as_of_ms,
            )
        )

    summary = sources_health[0]["source_health"] if sources_health else "UNKNOWN"
    if fetch in ("error", "timeout", "denied"):
        left_card = _left_card_from_primary(None, source_error=True)
        return {
            "capability": CAP_SEMANTICS,
            "status": "error",
            "as_of": _now_iso(),
            "official_source_ingestion": INGESTION_CONNECTED,
            "source_registry": list(registry.keys()),
            "sources_health": sources_health,
            "source_health_summary": "SOURCE_ERROR",
            "event_state": "UNKNOWN",
            "observation_state": "SOURCE_ERROR",
            "last_observed_at": None,
            "decision_events": "NONE",
            "primary_event_id": None,
            "active_candidate_count": 0,
            "items": [],
            "left_card": left_card,
            "right_evidence": {
                "status": "error",
                "title": "EVENT INTELLIGENCE",
                "source_health": "SOURCE_ERROR",
                "event_state": "UNKNOWN",
                "message": "EVENT TRUTH UNKNOWN · NO NEW BOOST",
                "layers": {},
            },
            "disclaimer": "READ ONLY · SOURCE ERROR",
        }

    items: List[Dict[str, Any]] = []
    if fixture_pipeline:
        ledger = EventTruthLedger()
        market_by_key: Dict[str, Dict[str, Any]] = {}
        for entry in fixture_pipeline:
            obs = entry.get("observation") or {}
            at_ms = entry.get("observed_at_ms") or as_of_ms
            ekey = obs.get("event_key") or entry.get("event_key")
            if ekey and entry.get("market_context"):
                market_by_key[ekey] = entry["market_context"]
            if entry.get("append_revision"):
                ledger.append_revision(ekey, obs, observed_at_ms=at_ms)
            elif entry.get("retraction"):
                ledger.append_retraction(
                    ekey,
                    observed_at_ms=at_ms,
                    source_id=obs.get("source_id", "BLS"),
                )
            else:
                ledger.ingest_observation(obs, observed_at_ms=at_ms)

        for key in ledger.chains:
            truth = ledger.truth_as_of(key, as_of_ms)
            if not truth:
                continue
            items.append(
                _project_event_item(
                    truth,
                    btc_trend=btc_trend,
                    eth_trend=eth_trend,
                    market_context=market_by_key.get(key, {}),
                    market_freshness=market_freshness,
                    as_of_ms=as_of_ms,
                )
            )

    primary = _select_primary(items)
    left_card = _left_card_from_primary(
        primary,
        no_event=not items,
    )

    right = {
        "status": "ok" if items else "no_event",
        "title": "EVENT INTELLIGENCE",
        "source_health": "NO_EVENT_OBSERVED" if not items else "OK",
        "last_observed_at": primary["right"]["what_happened"]["first_observed_at"] if primary else None,
        "decision_events": "NONE" if not items else "ACTIVE",
        "layers": primary["right"] if primary else {},
        "items_summary": [
            {
                "event_id": it["event_id"],
                "title": it["left"]["title"],
                "grade_label": it["left"]["grade_label"],
                "headline_action": it["left"]["headline_action"],
                "tone": it["left"]["tone"],
            }
            for it in items
        ],
        "footer": {
            "eligible_not_active": "ELIGIBLE ≠ ACTIVE",
            "read_only": "READ ONLY",
            "execution_denied": "EXECUTION DENIED",
        },
    }

    return {
        "capability": CAP_SEMANTICS,
        "status": "ok" if items else "no_event",
        "as_of": _now_iso(),
        "official_source_ingestion": INGESTION_CONNECTED,
        "source_registry": list(registry.keys()),
        "sources_health": sources_health,
        "source_health_summary": "NO_EVENT_OBSERVED" if not items else "OK",
        "event_state": "OK",
        "observation_state": "NO_EVENT_OBSERVED" if not items else "OK",
        "last_observed_at": right.get("last_observed_at"),
        "decision_events": "NONE" if not items else "ACTIVE",
        "primary_event_id": primary["event_id"] if primary else None,
        "active_candidate_count": len(items),
        "items": items,
        "left_card": left_card,
        "right_evidence": right,
        "disclaimer": "READ ONLY · ELIGIBLE ≠ ACTIVE · P3 HOLD",
    }


def build_event_snapshot(**kwargs: Any) -> Dict[str, Any]:
    """Observatory-compatible entry — replaces static placeholder."""
    return build_event_observatory_snapshot(**kwargs)
