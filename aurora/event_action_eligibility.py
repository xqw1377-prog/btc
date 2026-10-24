"""P2-C.2 Event Action Eligibility — read-only candidate layer.

NOT execution. NOT target weights. NOT order quantities.

Three pure function layers:
  C2-A  assess_impact()       → EventImpactAssessment
  C2-B  assess_priced_in()    → PricedInAssessment
  C2-C  assess_action_eligibility() → EventActionEligibilityCandidate

FROZEN:
  impact != probability != confidence
  priced_in anchor = first_observed_at (not ex-post price low)
  ELIGIBLE ≠ boost amount
  ACTIVE = UNREACHABLE_BY_POLICY
  RISK_OFF_ELIGIBLE ≠ OPEN SHORT
  positive boost requires trend alignment; defensive risk-off does NOT
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from aurora.event_intelligence_harness import ACTIVE_UNREACHABLE
from aurora.event_truth import LookaheadViolation, SOURCE_REGISTRY

__all__ = [
    "LookaheadViolation",
    "HARNESS_KIND",
    "ACTIVE_UNREACHABLE",
    "FORBIDDEN_OUTPUT_KEYS",
    "assess_impact",
    "assess_priced_in",
    "assess_action_eligibility",
    "evaluate_event_eligibility",
    "get_event_class_policies",
    "get_event_class_policy",
]

HARNESS_KIND = "EVENT_ACTION_ELIGIBILITY_CONTRACT"
POLICY_HASH_DEFAULT = "p2-c2-v1"

EVIDENCE_GRADES = ("E0", "E1", "E2", "E3")
DIRECTIONS = ("POSITIVE", "NEGATIVE", "NEUTRAL", "UNKNOWN")
PRICED_IN_STATES = ("NONE", "PARTIAL", "MOST", "UNKNOWN")
ACTION_STATES = ("NONE", "WATCH", "CONFIRMED", "ELIGIBLE", "RISK_OFF")
BOOST_ELIGIBILITY = (
    "NONE",
    "WATCH_ONLY",
    "CONFIRMED_FACT",
    "EVENT_BOOST_ELIGIBLE",
    "RISK_OFF_ELIGIBLE",
    "NO_BOOST",
)

RISK_OFF_OVERLAYS = (
    "BLOCK_NEW_LONG_ELIGIBLE",
    "REMOVE_EVENT_INCREMENT_ELIGIBLE",
    "REDUCE_OVERLAY_ELIGIBLE",
)

# PROVISIONAL_E3_PARAM — mechanism frozen; numeric bands not Alpha claims
PRICED_IN_NONE_ATR = 0.5
PRICED_IN_MOST_ATR = 1.5
TREND_BOOST_MIN_LEVEL = 3  # PROVISIONAL_E3_PARAM — positive boost gate

FORBIDDEN_INPUT_FIELDS = frozenset({
    "target_leverage",
    "target_weight",
    "account_balance",
    "margin_available",
    "execute_authorized",
    "ex_post_revision",
    "future_price_reaction",
    "lookahead_knowledge",
})

FORBIDDEN_OUTPUT_KEYS: FrozenSet[str] = frozenset({
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
    "extra_risk",
    "extra_risk_pct",
    "nav_increment",
})

EVENT_CLASS_POLICIES: Dict[str, Dict[str, Any]] = {
    "FED_RATE_DECISION": {
        "event_class": "FED_RATE_DECISION",
        "allowed_assets": ("BTC", "ETH"),
        "required_fields": ("factual_claim",),
        "transmission_templates": ["rate_path", "liquidity"],
        "eligible_for_positive_boost": True,
        "eligible_for_risk_off": True,
        "systemic_risk": False,
    },
    "CPI_RELEASE": {
        "event_class": "CPI_RELEASE",
        "allowed_assets": ("BTC", "ETH"),
        "required_fields": ("actual_value",),
        "transmission_templates": ["inflation", "rate_path"],
        "eligible_for_positive_boost": True,
        "eligible_for_risk_off": True,
        "systemic_risk": False,
    },
    "NFP_RELEASE": {
        "event_class": "NFP_RELEASE",
        "allowed_assets": ("BTC", "ETH"),
        "required_fields": ("actual_value",),
        "transmission_templates": ["employment", "rate_path"],
        "eligible_for_positive_boost": True,
        "eligible_for_risk_off": True,
        "systemic_risk": False,
    },
    "SEC_CRYPTO_REGULATION": {
        "event_class": "SEC_CRYPTO_REGULATION",
        "allowed_assets": ("BTC", "ETH"),
        "required_fields": ("factual_claim",),
        "transmission_templates": ["regulatory", "access"],
        "eligible_for_positive_boost": False,
        "eligible_for_risk_off": True,
        "systemic_risk": False,
    },
    "ETF_APPROVAL_REJECTION": {
        "event_class": "ETF_APPROVAL_REJECTION",
        "allowed_assets": ("BTC", "ETH"),
        "required_fields": ("factual_claim",),
        "transmission_templates": ["access", "flows"],
        "eligible_for_positive_boost": True,
        "eligible_for_risk_off": True,
        "systemic_risk": False,
        "requires_formal_document": True,
    },
    "MAJOR_EXCHANGE_FAILURE": {
        "event_class": "MAJOR_EXCHANGE_FAILURE",
        "allowed_assets": ("BTC", "ETH"),
        "required_fields": ("factual_claim",),
        "transmission_templates": ["counterparty", "liquidity"],
        "eligible_for_positive_boost": False,
        "eligible_for_risk_off": True,
        "systemic_risk": True,
    },
    "SYSTEMIC_HACK": {
        "event_class": "SYSTEMIC_HACK",
        "allowed_assets": ("BTC", "ETH"),
        "required_fields": ("factual_claim",),
        "transmission_templates": ["security", "confidence"],
        "eligible_for_positive_boost": False,
        "eligible_for_risk_off": True,
        "systemic_risk": True,
    },
    "OFFICIAL_SOCIAL_RUMOR": {
        "event_class": "OFFICIAL_SOCIAL_RUMOR",
        "allowed_assets": ("BTC", "ETH"),
        "required_fields": (),
        "transmission_templates": [],
        "eligible_for_positive_boost": False,
        "eligible_for_risk_off": False,
        "systemic_risk": False,
        "requires_formal_document": True,
        "never_boost": True,
    },
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


def _level_num(level: Optional[str]) -> int:
    if not level:
        return 0
    for ch in str(level):
        if ch.isdigit():
            return int(ch)
    return 0


def _reject_forbidden_input(extra: Dict[str, Any]) -> None:
    bad = FORBIDDEN_INPUT_FIELDS.intersection(extra.keys())
    if bad:
        raise LookaheadViolation(f"LOOKAHEAD_REJECTED: forbidden input {sorted(bad)}")


def _reject_forbidden_output(out: Dict[str, Any]) -> None:
    def walk(obj: Any, path: str = "") -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in FORBIDDEN_OUTPUT_KEYS:
                    raise ValueError(f"forbidden output field: {path}.{k}" if path else k)
                walk(v, f"{path}.{k}" if path else k)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                walk(item, f"{path}[{i}]")

    walk(out)


def get_event_class_policy(event_class: str) -> Optional[Dict[str, Any]]:
    key = (event_class or "").upper().replace(" ", "_")
    aliases = {
        "CPI": "CPI_RELEASE",
        "NFP": "NFP_RELEASE",
        "FOMC": "FED_RATE_DECISION",
        "ETF": "ETF_APPROVAL_REJECTION",
    }
    return EVENT_CLASS_POLICIES.get(key) or EVENT_CLASS_POLICIES.get(aliases.get(key, ""))


def _has_formal_document(event_truth: Dict[str, Any]) -> bool:
    payload = event_truth.get("payload") or {}
    if payload.get("formal_document"):
        return True
    stage = (event_truth.get("stage") or "").upper()
    source_id = event_truth.get("source_id") or ""
    if stage == "EVENT_TRUTH" and source_id in SOURCE_REGISTRY:
        return True
    return bool(payload.get("sec_filing_id") or payload.get("document_url"))


def _derive_evidence_grade(
    event_truth: Dict[str, Any],
    policy: Optional[Dict[str, Any]],
    impact: Dict[str, Any],
) -> str:
    if event_truth.get("retracted"):
        return "E0"
    if policy and policy.get("never_boost"):
        return "E0"
    if policy and policy.get("requires_formal_document") and not _has_formal_document(event_truth):
        return "E0"
    quality = (event_truth.get("source_quality") or "").upper()
    if quality in ("UNVERIFIED", "RUMOR", "SOCIAL_ONLY"):
        return "E0"
    if (event_truth.get("stage") or "") == "EXTRACTED_CANDIDATE":
        return "E0"
    if not policy:
        return "E0"
    for field in policy.get("required_fields") or ():
        if event_truth.get(field) is None and field not in (event_truth.get("payload") or {}):
            return "E0"
    btc_dir = impact.get("btc_direction", "UNKNOWN")
    eth_dir = impact.get("eth_direction", "UNKNOWN")
    if btc_dir == "UNKNOWN" and eth_dir == "UNKNOWN":
        if event_truth.get("source_id") in SOURCE_REGISTRY or quality == "OFFICIAL":
            return "E1"
        return "E0"
    if impact.get("transmission_path") and len(impact["transmission_path"]) >= 1:
        if btc_dir != "UNKNOWN" or eth_dir != "UNKNOWN":
            return "E3"
        return "E2"
    return "E2"


def _macro_direction_from_surprise(event_truth: Dict[str, Any]) -> Tuple[str, str, int, int]:
    """Policy-driven direction from truth fields — not LLM."""
    surprise = event_truth.get("surprise")
    actual = event_truth.get("actual_value")
    previous = event_truth.get("previous_value")
    event_class = (event_truth.get("event_class") or "").upper()

    if surprise is not None:
        if surprise > 0:
            btc_dir, eth_dir = "NEGATIVE", "NEGATIVE"
            btc_impact, eth_impact = -4, -3
        elif surprise < 0:
            btc_dir, eth_dir = "POSITIVE", "POSITIVE"
            btc_impact, eth_impact = 4, 3
        else:
            btc_dir, eth_dir = "NEUTRAL", "NEUTRAL"
            btc_impact, eth_impact = 0, 0
        return btc_dir, eth_dir, btc_impact, eth_impact

    if actual is not None and previous is not None:
        delta = actual - previous
        if event_class in ("CPI", "CPI_RELEASE", "NFP", "NFP_RELEASE"):
            if delta > 0:
                return "NEGATIVE", "NEGATIVE", -4, -3
            if delta < 0:
                return "POSITIVE", "POSITIVE", 4, 3
            return "NEUTRAL", "NEUTRAL", 0, 0

    return "UNKNOWN", "UNKNOWN", 0, 0


def _systemic_direction(event_class: str) -> Tuple[str, str, int, int]:
    cls = event_class.upper()
    if cls in ("MAJOR_EXCHANGE_FAILURE", "SYSTEMIC_HACK"):
        return "NEGATIVE", "NEGATIVE", -5, -5
    if cls in ("ETF_APPROVAL_REJECTION",):
        return "NEGATIVE", "NEGATIVE", -4, -3
    if cls in ("ETF_APPROVAL",):
        return "POSITIVE", "POSITIVE", 4, 3
    return "UNKNOWN", "UNKNOWN", 0, 0


def assess_impact(
    event_truth: Dict[str, Any],
    *,
    as_of: Optional[str] = None,
    policy_override: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """C2-A — Impact assessment from class policy + truth fields."""
    event_class = event_truth.get("event_class") or "UNKNOWN"
    policy = policy_override or get_event_class_policy(event_class)
    blockers: List[str] = []
    reasons: List[str] = []

    if policy and policy.get("never_boost"):
        reasons.append("policy marks never_boost — social/unverified channel")

    cls_upper = event_class.upper()
    if policy and policy.get("systemic_risk"):
        btc_dir, eth_dir, btc_imp, eth_imp = _systemic_direction(cls_upper)
        transmission = list(policy.get("transmission_templates") or [])
    elif cls_upper in ("CPI", "CPI_RELEASE", "NFP", "NFP_RELEASE", "PCE", "GDP"):
        btc_dir, eth_dir, btc_imp, eth_imp = _macro_direction_from_surprise(event_truth)
        transmission = list((policy or {}).get("transmission_templates") or ["macro"])
    else:
        btc_dir, eth_dir, btc_imp, eth_imp = _systemic_direction(cls_upper)
        transmission = list((policy or {}).get("transmission_templates") or [])

    if btc_dir == "UNKNOWN" and eth_dir == "UNKNOWN":
        blockers.append("DIRECTION_UNKNOWN")

    opposing: List[str] = []
    if event_truth.get("consensus_truth_state") == "UNKNOWN":
        opposing.append("consensus_unknown")

    grade = _derive_evidence_grade(event_truth, policy, {
        "btc_direction": btc_dir,
        "eth_direction": eth_dir,
        "transmission_path": transmission,
    })

    return {
        "layer": "C2-A",
        "event_key": event_truth.get("event_key"),
        "event_version": event_truth.get("event_version"),
        "as_of": as_of or event_truth.get("last_observed_at") or _now_iso(),
        "evidence_grade": grade,
        "btc_direction": btc_dir,
        "eth_direction": eth_dir,
        "btc_impact": btc_imp if btc_dir != "UNKNOWN" else "UNKNOWN",
        "eth_impact": eth_imp if eth_dir != "UNKNOWN" else "UNKNOWN",
        "transmission_path": transmission,
        "opposing_evidence": opposing,
        "assessment_version": "p2-c2-impact-v1",
        "reasons": reasons,
        "blockers": blockers,
        "impact_is_not_probability": True,
    }


def assess_priced_in(
    event_truth: Dict[str, Any],
    market_context: Dict[str, Any],
    *,
    as_of_ms: Optional[int] = None,
) -> Dict[str, Any]:
    """C2-B — Priced-in from vol-normalized reaction anchored at first_observed_at."""
    anchor_iso = event_truth.get("first_observed_at")
    anchor_ms = _iso_to_ms(anchor_iso)
    assessment_ms = market_context.get("assessment_time_ms") or as_of_ms
    reasons: List[str] = []

    if market_context.get("future_price_reaction"):
        raise LookaheadViolation("LOOKAHEAD_REJECTED: future_price_reaction forbidden")

    post_ts = market_context.get("post_observation_ms")
    if post_ts and as_of_ms and post_ts > as_of_ms:
        raise LookaheadViolation("LOOKAHEAD_REJECTED: post price after as_of")

    if anchor_ms and market_context.get("anchor_time_ms"):
        if market_context["anchor_time_ms"] != anchor_ms:
            reasons.append("anchor_time overridden to first_observed_at")
    anchor_ms = anchor_ms or market_context.get("anchor_time_ms")

    btc_pre = market_context.get("btc_pre_price")
    btc_post = market_context.get("btc_post_price")
    eth_pre = market_context.get("eth_pre_price")
    eth_post = market_context.get("eth_post_price")
    btc_atr = market_context.get("btc_atr") or 1.0
    eth_atr = market_context.get("eth_atr") or 1.0

    btc_move = None
    eth_move = None
    btc_vol = None
    eth_vol = None
    if btc_pre is not None and btc_post is not None and btc_atr:
        btc_move = btc_post - btc_pre
        btc_vol = abs(btc_move) / btc_atr
    if eth_pre is not None and eth_post is not None and eth_atr:
        eth_move = eth_post - eth_pre
        eth_vol = abs(eth_move) / eth_atr

    chase = max(v for v in (btc_vol, eth_vol) if v is not None) if (btc_vol or eth_vol) else None

    priced_in = "UNKNOWN"
    if chase is None:
        reasons.append("insufficient price context — priced_in UNKNOWN")
    else:
        if chase < PRICED_IN_NONE_ATR:
            priced_in = "NONE"
            reasons.append(f"chase {chase:.2f} ATR < {PRICED_IN_NONE_ATR} (PROVISIONAL_E3_PARAM)")
        elif chase <= PRICED_IN_MOST_ATR:
            priced_in = "PARTIAL"
            reasons.append(f"chase {chase:.2f} ATR partial band (PROVISIONAL_E3_PARAM)")
        else:
            priced_in = "MOST"
            reasons.append(f"chase {chase:.2f} ATR >= {PRICED_IN_MOST_ATR} (PROVISIONAL_E3_PARAM)")

    freshness = market_context.get("freshness") or event_truth.get("freshness") or "unknown"

    return {
        "layer": "C2-B",
        "event_key": event_truth.get("event_key"),
        "event_version": event_truth.get("event_version"),
        "anchor_time": anchor_iso,
        "assessment_time": _ms_to_iso(assessment_ms) if assessment_ms else _now_iso(),
        "btc_pre_move": btc_move,
        "btc_post_move": btc_post,
        "eth_pre_move": eth_move,
        "eth_post_move": eth_post,
        "btc_move_in_vol_units": btc_vol,
        "eth_move_in_vol_units": eth_vol,
        "chase_distance": chase,
        "priced_in": priced_in,
        "freshness": freshness,
        "reasons": reasons,
        "mechanism": "vol_normalized_chase_from_first_observed_at",
        "thresholds_provisional": True,
    }


def _ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _trend_aligned(impact: Dict[str, Any], trend: Dict[str, Any]) -> bool:
    btc_dir = impact.get("btc_direction")
    btc_level = _level_num((trend.get("btc") or {}).get("level"))
    if btc_dir == "POSITIVE" and btc_level >= TREND_BOOST_MIN_LEVEL:
        return True
    if btc_dir == "NEGATIVE" and btc_level <= 2:
        return True
    if btc_dir == "NEUTRAL":
        return btc_level >= TREND_BOOST_MIN_LEVEL
    return False


def _eligibility_fingerprint(
    event_truth: Dict[str, Any],
    impact: Dict[str, Any],
    priced_in: Dict[str, Any],
    trend: Dict[str, Any],
) -> str:
    payload = {
        "event_key": event_truth.get("event_key"),
        "event_version": event_truth.get("event_version"),
        "btc_level": (trend.get("btc") or {}).get("level"),
        "eth_level": (trend.get("eth") or {}).get("level"),
        "trend_epoch": trend.get("epoch"),
        "priced_in": priced_in.get("priced_in"),
        "chase": priced_in.get("chase_distance"),
        "grade": impact.get("evidence_grade"),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]


def assess_action_eligibility(
    *,
    event_truth: Dict[str, Any],
    event_impact: Dict[str, Any],
    priced_in: Dict[str, Any],
    btc_trend_snapshot: Dict[str, Any],
    eth_trend_snapshot: Optional[Dict[str, Any]] = None,
    market_freshness: Optional[str] = None,
    previous_event_state: Optional[Dict[str, Any]] = None,
    policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """C2-C — asymmetric eligibility state machine."""
    trend = {"btc": btc_trend_snapshot, "eth": eth_trend_snapshot or {}}
    policy = policy or get_event_class_policy(event_truth.get("event_class") or "")
    reasons: List[str] = []
    blockers: List[str] = []
    risk_off_overlays: List[str] = []

    grade = event_impact.get("evidence_grade", "E0")
    pi = (priced_in.get("priced_in") or "UNKNOWN").upper()
    freshness = (market_freshness or priced_in.get("freshness") or "unknown").lower()
    btc_level = _level_num((trend.get("btc") or {}).get("level"))
    conflict = bool(event_truth.get("conflict"))
    stale_truth = freshness in ("stale",) or (event_truth.get("freshness") or "").lower() == "stale"

    btc_dir = event_impact.get("btc_direction", "UNKNOWN")
    eth_dir = event_impact.get("eth_direction", "UNKNOWN")
    negative = (
        btc_dir == "NEGATIVE"
        or eth_dir == "NEGATIVE"
        or (isinstance(event_impact.get("btc_impact"), (int, float)) and event_impact["btc_impact"] < 0)
        or (isinstance(event_impact.get("eth_impact"), (int, float)) and event_impact["eth_impact"] < 0)
    )
    systemic = bool(policy and policy.get("systemic_risk"))

    action_state = "WATCH"
    boost = "WATCH_ONLY"
    event_increment_request = "NONE"

    if event_truth.get("retracted"):
        reasons.append("RETRACTED — eligibility revoked")
        blockers.append("EVENT_RETRACTED")
        return _pack_eligibility(
            action_state="NONE",
            boost_eligibility="NONE",
            event_increment_request="NONE",
            reasons=reasons,
            blockers=blockers,
            risk_off_overlays=[],
            event_truth=event_truth,
            event_impact=event_impact,
            priced_in=priced_in,
            trend=trend,
            previous_event_state=previous_event_state,
        )

    if conflict:
        blockers.append("TRUTH_CONFLICT")
        reasons.append("conflicting authoritative sources — UNKNOWN")
        return _pack_eligibility(
            action_state="WATCH",
            boost_eligibility="NO_BOOST",
            event_increment_request="NONE",
            reasons=reasons,
            blockers=blockers,
            risk_off_overlays=[],
            event_truth=event_truth,
            event_impact=event_impact,
            priced_in=priced_in,
            trend=trend,
            previous_event_state=previous_event_state,
        )

    if policy and policy.get("never_boost"):
        reasons.append("unverified social — never boost (SEC-style guard)")
        blockers.append("NO_FORMAL_DOCUMENT")
        return _pack_eligibility(
            action_state="WATCH",
            boost_eligibility="WATCH_ONLY",
            event_increment_request="NONE",
            reasons=reasons,
            blockers=blockers,
            risk_off_overlays=[],
            event_truth=event_truth,
            event_impact=event_impact,
            priced_in=priced_in,
            trend=trend,
            previous_event_state=previous_event_state,
        )

    if grade == "E0":
        reasons.append("E0 — insufficient evidence")
        return _pack_eligibility(
            action_state="WATCH",
            boost_eligibility="WATCH_ONLY",
            event_increment_request="NONE",
            reasons=reasons,
            blockers=blockers,
            risk_off_overlays=[],
            event_truth=event_truth,
            event_impact=event_impact,
            priced_in=priced_in,
            trend=trend,
            previous_event_state=previous_event_state,
        )

    if grade == "E1":
        reasons.append("E1 — fact confirmed, direction unclear")
        blockers.append("DIRECTION_UNKNOWN")
        return _pack_eligibility(
            action_state="CONFIRMED",
            boost_eligibility="CONFIRMED_FACT",
            event_increment_request="NONE",
            reasons=reasons,
            blockers=blockers,
            risk_off_overlays=[],
            event_truth=event_truth,
            event_impact=event_impact,
            priced_in=priced_in,
            trend=trend,
            previous_event_state=previous_event_state,
        )

    if negative and grade in ("E2", "E3") and (systemic or policy):
        reasons.append("E3 negative systemic — RISK_OFF_ELIGIBLE, no short")
        blockers.append("NO_SHORT_AUTHORITY")
        risk_off_overlays = list(RISK_OFF_OVERLAYS)
        return _pack_eligibility(
            action_state="RISK_OFF",
            boost_eligibility="RISK_OFF_ELIGIBLE",
            event_increment_request="NONE",
            reasons=reasons,
            blockers=blockers,
            risk_off_overlays=risk_off_overlays,
            event_truth=event_truth,
            event_impact=event_impact,
            priced_in=priced_in,
            trend=trend,
            previous_event_state=previous_event_state,
        )

    if stale_truth:
        reasons.append("truth/market STALE — no new boost")
        blockers.append("FRESHNESS_STALE")
        return _pack_eligibility(
            action_state="CONFIRMED",
            boost_eligibility="NO_BOOST",
            event_increment_request="NONE",
            reasons=reasons,
            blockers=blockers,
            risk_off_overlays=[],
            event_truth=event_truth,
            event_impact=event_impact,
            priced_in=priced_in,
            trend=trend,
            previous_event_state=previous_event_state,
        )

    if pi == "MOST":
        reasons.append("priced_in MOST — NO BOOST")
        blockers.append("PRICED_IN_MOST")
        return _pack_eligibility(
            action_state="CONFIRMED",
            boost_eligibility="NO_BOOST",
            event_increment_request="NONE",
            reasons=reasons,
            blockers=blockers,
            risk_off_overlays=[],
            event_truth=event_truth,
            event_impact=event_impact,
            priced_in=priced_in,
            trend=trend,
            previous_event_state=previous_event_state,
        )

    if pi == "UNKNOWN":
        reasons.append("priced_in UNKNOWN — cannot auto ELIGIBLE")
        blockers.append("PRICED_IN_UNKNOWN")
        return _pack_eligibility(
            action_state="CONFIRMED",
            boost_eligibility="NO_BOOST",
            event_increment_request="NONE",
            reasons=reasons,
            blockers=blockers,
            risk_off_overlays=[],
            event_truth=event_truth,
            event_impact=event_impact,
            priced_in=priced_in,
            trend=trend,
            previous_event_state=previous_event_state,
        )

    if grade == "E3" and btc_level < TREND_BOOST_MIN_LEVEL:
        reasons.append(f"E3 but BTC trend below L{TREND_BOOST_MIN_LEVEL}")
        blockers.append("TREND_NOT_CONFIRMED")
        return _pack_eligibility(
            action_state="CONFIRMED",
            boost_eligibility="NO_BOOST",
            event_increment_request="NONE",
            reasons=reasons,
            blockers=blockers,
            risk_off_overlays=[],
            event_truth=event_truth,
            event_impact=event_impact,
            priced_in=priced_in,
            trend=trend,
            previous_event_state=previous_event_state,
        )

    if freshness in ("stale", "unknown"):
        reasons.append(f"freshness {freshness} — block boost")
        blockers.append("FRESHNESS_FAIL")
        return _pack_eligibility(
            action_state="CONFIRMED",
            boost_eligibility="NO_BOOST",
            event_increment_request="NONE",
            reasons=reasons,
            blockers=blockers,
            risk_off_overlays=[],
            event_truth=event_truth,
            event_impact=event_impact,
            priced_in=priced_in,
            trend=trend,
            previous_event_state=previous_event_state,
        )

    aligned = _trend_aligned(event_impact, trend)
    if (
        grade == "E3"
        and not negative
        and policy
        and policy.get("eligible_for_positive_boost")
        and btc_level >= TREND_BOOST_MIN_LEVEL
        and aligned
        and pi in ("NONE", "PARTIAL")
    ):
        reasons.append("E3 + trend aligned + priced_in acceptable")
        return _pack_eligibility(
            action_state="ELIGIBLE",
            boost_eligibility="EVENT_BOOST_ELIGIBLE",
            event_increment_request="ELIGIBLE",
            reasons=reasons,
            blockers=blockers,
            risk_off_overlays=[],
            event_truth=event_truth,
            event_impact=event_impact,
            priced_in=priced_in,
            trend=trend,
            previous_event_state=previous_event_state,
        )

    if grade == "E2":
        reasons.append("E2 — awaiting full E3 / gates")
        return _pack_eligibility(
            action_state="CONFIRMED",
            boost_eligibility="NO_BOOST",
            event_increment_request="NONE",
            reasons=reasons,
            blockers=blockers,
            risk_off_overlays=[],
            event_truth=event_truth,
            event_impact=event_impact,
            priced_in=priced_in,
            trend=trend,
            previous_event_state=previous_event_state,
        )

    reasons.append("default WATCH")
    return _pack_eligibility(
        action_state="WATCH",
        boost_eligibility="WATCH_ONLY",
        event_increment_request="NONE",
        reasons=reasons,
        blockers=blockers,
        risk_off_overlays=[],
        event_truth=event_truth,
        event_impact=event_impact,
        priced_in=priced_in,
        trend=trend,
        previous_event_state=previous_event_state,
    )


def _pack_eligibility(
    *,
    action_state: str,
    boost_eligibility: str,
    event_increment_request: str,
    reasons: List[str],
    blockers: List[str],
    risk_off_overlays: List[str],
    event_truth: Dict[str, Any],
    event_impact: Dict[str, Any],
    priced_in: Dict[str, Any],
    trend: Dict[str, Any],
    previous_event_state: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    fp = _eligibility_fingerprint(event_truth, event_impact, priced_in, trend)
    idempotent = False
    if previous_event_state:
        if previous_event_state.get("fingerprint") == fp:
            idempotent = True
            blockers = list(blockers) + ["IDEMPOTENT"]
            reasons = list(reasons) + ["same event_version + trend epoch + price context"]
            boost_eligibility = "NO_BOOST"
            if previous_event_state.get("action_state"):
                action_state = previous_event_state["action_state"]
            event_increment_request = "NONE"

    return {
        "layer": "C2-C",
        "action_state": action_state,
        "boost_eligibility": boost_eligibility,
        "event_increment_request": event_increment_request,
        "active_policy": ACTIVE_UNREACHABLE,
        "active_unreachable": ACTIVE_UNREACHABLE,
        "risk_off_overlays": risk_off_overlays,
        "reasons": reasons,
        "blockers": blockers,
        "fingerprint": fp,
        "idempotent": idempotent,
        "eligible_not_active": action_state == "ELIGIBLE",
    }


def evaluate_event_eligibility(inp: Dict[str, Any]) -> Dict[str, Any]:
    """Orchestrate C2-A → C2-B → C2-C from EventEligibilityInput."""
    extra = {k: v for k, v in inp.items() if k not in (
        "case_id", "event_truth", "market_context", "btc_trend_snapshot",
        "eth_trend_snapshot", "market_freshness", "previous_event_state",
        "policy_version", "policy_override", "as_of", "as_of_ms",
        "event_impact_override", "priced_in_override",
    )}
    _reject_forbidden_input(extra)

    case_id = inp.get("case_id", "UNKNOWN")
    event_truth = dict(inp.get("event_truth") or {})
    market_context = dict(inp.get("market_context") or {})
    btc_trend = dict(inp.get("btc_trend_snapshot") or {})
    eth_trend = dict(inp.get("eth_trend_snapshot") or {})
    previous = dict(inp.get("previous_event_state") or {})
    as_of = inp.get("as_of")
    as_of_ms = inp.get("as_of_ms")

    impact = inp.get("event_impact_override") or assess_impact(
        event_truth,
        as_of=as_of,
        policy_override=inp.get("policy_override"),
    )
    priced = inp.get("priced_in_override") or assess_priced_in(
        event_truth, market_context, as_of_ms=as_of_ms,
    )
    eligibility = assess_action_eligibility(
        event_truth=event_truth,
        event_impact=impact,
        priced_in=priced,
        btc_trend_snapshot=btc_trend,
        eth_trend_snapshot=eth_trend,
        market_freshness=inp.get("market_freshness"),
        previous_event_state=previous,
        policy=inp.get("policy_override") or get_event_class_policy(
            event_truth.get("event_class") or ""
        ),
    )

    out = {
        "harness_kind": HARNESS_KIND,
        "case_id": case_id,
        "policy_version": inp.get("policy_version") or POLICY_HASH_DEFAULT,
        "as_of": as_of or event_truth.get("last_observed_at") or _now_iso(),
        "event_impact_assessment": impact,
        "priced_in_assessment": priced,
        "event_action_eligibility": eligibility,
        "event_truth_summary": {
            "event_key": event_truth.get("event_key"),
            "event_version": event_truth.get("event_version"),
            "event_class": event_truth.get("event_class"),
            "retracted": bool(event_truth.get("retracted")),
            "first_observed_at": event_truth.get("first_observed_at"),
        },
        "reasons": eligibility.get("reasons", []),
        "blockers": eligibility.get("blockers", []),
        "idempotent": eligibility.get("idempotent", False),
    }
    _reject_forbidden_output(out)
    return out


def get_event_class_policies() -> Dict[str, Dict[str, Any]]:
    return dict(EVENT_CLASS_POLICIES)
