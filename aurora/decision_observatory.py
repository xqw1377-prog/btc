"""P3-R2 Decision Observatory projection — brain candidate → observatory.decision bundle.

NOT a second decision pass. NOT RiskGate. NOT execution.

FROZEN:
  Frontend mirrors left_card + right_evidence only
  CURRENT never fabricated from wallet balances
  TARGET CANDIDATE + DELTA UNAVAILABLE is valid combined state
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from aurora.decision_brain import build_normalized_decision_input, default_decision_policy, evaluate_decision
from aurora.decision_brain_entry_gate import (
    normalize_event_decision_input,
    normalize_trend_decision_input,
    normalize_value_decision_input,
)

CAP_DECISION = "READ-ONLY-DECISION"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _account_truth_from_exchange(
    exchange: Dict[str, Any],
    account_meta: Dict[str, Any],
) -> Dict[str, str]:
    status = (account_meta or {}).get("status") or exchange.get("status") or "unknown"
    account_unknown = status != "ok"
    positions = exchange.get("positions") or "UNKNOWN"
    position_unknown = positions == "UNKNOWN" or account_unknown
    return {
        "account": "UNKNOWN" if account_unknown else "KNOWN",
        "position": "UNKNOWN" if position_unknown else "KNOWN",
        "protection": "UNKNOWN",
    }


def _authoritative_current(
    exchange: Dict[str, Any],
    account_truth: Dict[str, str],
    *,
    override: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    if override:
        return dict(override)
    if account_truth.get("account") != "KNOWN":
        return None
    mix = (exchange.get("actual_mix") or {})
    pct = mix.get("percent")
    if not pct or pct.get("btc") is None:
        return None
    return {
        "status": "KNOWN",
        "btc": float(pct["btc"]),
        "eth": float(pct.get("eth") or 0),
        "usdt": float(pct.get("usdt") or 0),
        "btc_overlay": float(mix.get("btc_overlay") or 0),
        "eth_overlay": float(mix.get("eth_overlay") or 0),
        "event_increment": float(mix.get("event_increment") or 0),
    }


def _spot_label(action: str) -> str:
    m = {
        "NO_CHANGE": "HOLD",
        "WATCH_ETH": "WATCH ETH",
        "REALLOCATE_ETH_ELIGIBLE": "INCREASE ETH ELIGIBLE",
        "REDUCE_OR_CLOSE": "REDUCE EXPOSURE",
        "NO_REALLOCATION": "NO REALLOCATION",
    }
    return m.get(action or "", action or "—")


def _overlay_label(btc_action: str, eth_action: str) -> str:
    if btc_action == "CLOSE_OVERLAY":
        return "CLOSE OVERLAY CANDIDATE"
    if btc_action == "BLOCKED":
        return "BLOCKED"
    if btc_action == "INCREASE_CANDIDATE":
        return "BTC ELIGIBLE" + (" · ETH ELIGIBLE" if eth_action == "INCREASE_CANDIDATE" else "")
    return "NONE"


def _event_label(action: str, increment_req: str) -> str:
    if action == "RISK_OFF":
        return "RISK-OFF · NO INCREMENT"
    if increment_req == "ELIGIBLE":
        return "INCREMENT REQUEST ELIGIBLE"
    if action == "REMOVED":
        return "INCREMENT REMOVED"
    return "NO INCREMENT"


def _primary_blocker(blockers: List[str]) -> Optional[str]:
    for pref in (
        "ACCOUNT_TRUTH_UNKNOWN",
        "DELTA_REQUIRES_AUTHORITATIVE_CURRENT",
        "TREND_TRUTH_UNKNOWN",
        "PROTECTION_TRUTH_UNKNOWN",
        "POSITION_TRUTH_UNKNOWN",
    ):
        for b in blockers:
            if pref in b.upper().replace(" ", "_"):
                return b
    return blockers[0] if blockers else None


def _build_decision_trace(candidate: Dict[str, Any]) -> Dict[str, Any]:
    blockers = candidate.get("blockers") or []
    p0_fail = any(
        k in " ".join(blockers)
        for k in ("ACCOUNT_TRUTH", "POSITION_TRUTH", "PROTECTION_TRUTH", "P0:")
    )
    defensive = (
        candidate.get("event_action") == "RISK_OFF"
        or candidate.get("btc_overlay_action") == "CLOSE_OVERLAY"
        or candidate.get("spot_action") == "REDUCE_OR_CLOSE"
    )
    p2_detail = "NONE"
    winner = None
    if candidate.get("event_action") == "RISK_OFF":
        p2_detail = "RISK_OFF ELIGIBLE"
        winner = "P2"
    elif candidate.get("btc_overlay_action") == "CLOSE_OVERLAY":
        p2_detail = "THESIS INVALIDATION"
        winner = "P2"

    def _stage(name: str, status: str, detail: str = "") -> Dict[str, str]:
        return {"stage": name, "status": status, "detail": detail}

    stages = [
        _stage("P0 TRUTH", "FAIL" if p0_fail else "PASS"),
        _stage("P2 DEFENSIVE", p2_detail, "↑ WINNER" if winner == "P2" else ""),
    ]
    suppressed = "SUPPRESSED BY P2" if defensive and winner == "P2" else candidate.get("spot_action", "NONE")
    stages.append(_stage("P3 SPOT", suppressed))
    ovl = (
        "SUPPRESSED BY P2"
        if defensive and winner == "P2"
        else _overlay_label(
            candidate.get("btc_overlay_action", "HOLD"),
            candidate.get("eth_overlay_action", "HOLD"),
        )
    )
    stages.append(_stage("P4 TREND", ovl))
    stages.append(_stage("P5 EVENT", _event_label(
        candidate.get("event_action", "NONE"),
        candidate.get("event_increment_request", "NONE"),
    )))
    return {"stages": stages, "winner": winner}


def _build_left_card(candidate: Dict[str, Any], trace: Dict[str, Any]) -> Dict[str, Any]:
    cur = candidate.get("current_state") or {}
    tgt = candidate.get("target_state") or {}
    delta = candidate.get("delta_proposal") or {}
    blockers = candidate.get("blockers") or []

    target_status = tgt.get("status") or "UNKNOWN"
    delta_status = delta.get("status") or "UNAVAILABLE"

    if target_status == "CANDIDATE" and delta_status == "UNAVAILABLE":
        headline = "TARGET CANDIDATE"
    elif delta_status == "AVAILABLE":
        headline = "REALLOCATION CANDIDATE"
    elif target_status == "UNKNOWN":
        headline = "TARGET UNKNOWN"
    else:
        headline = "PORTFOLIO DECISION"

    direction = "偏向 ETH · 保持 BTC 核心"
    if candidate.get("spot_action") == "NO_CHANGE":
        direction = "保持 BTC 核心"
    elif candidate.get("event_action") == "RISK_OFF":
        direction = "防守优先"

    mirror_rows: List[Dict[str, Any]] = [
        {"label": "SPOT", "value": _spot_label(candidate.get("spot_action"))},
        {"label": "TREND OVERLAY", "value": _overlay_label(
            candidate.get("btc_overlay_action", "HOLD"),
            candidate.get("eth_overlay_action", "HOLD"),
        )},
        {"label": "EVENT", "value": _event_label(
            candidate.get("event_action", "NONE"),
            candidate.get("event_increment_request", "NONE"),
        )},
        {"label": "DELTA", "value": delta_status},
    ]

    if cur.get("status") == "KNOWN" and delta_status == "AVAILABLE":
        mirror_rows = [
            {"label": "CURRENT", "value": f"BTC {cur.get('btc')} · ETH {cur.get('eth')} · USDT {cur.get('usdt')}"},
            {"label": "TARGET", "value": f"BTC {tgt.get('btc')} · ETH {tgt.get('eth')} · USDT {tgt.get('usdt')}"},
        ]
        d_btc = delta.get("btc")
        d_eth = delta.get("eth")
        if d_btc is not None and d_btc < 0:
            mirror_rows.append({"label": "DELTA", "value": f"REDUCE BTC EXPOSURE {abs(d_btc):.0f}"})
        elif d_btc is not None and d_btc > 0:
            mirror_rows.append({"label": "DELTA", "value": f"INCREASE BTC EXPOSURE {d_btc:.0f}"})
        if d_eth is not None and d_eth > 0:
            mirror_rows.append({"label": "DELTA ETH", "value": f"INCREASE ETH EXPOSURE {d_eth:.0f}"})
        elif d_eth is not None and d_eth < 0:
            mirror_rows.append({"label": "DELTA ETH", "value": f"REDUCE ETH EXPOSURE {abs(d_eth):.0f}"})

    cluster = candidate.get("crypto_beta_cluster") or {}
    primary = _primary_blocker(blockers)

    return {
        "index": "05",
        "title": "PORTFOLIO DECISION",
        "subtitle": "统一资本判断",
        "headlines": [headline, direction],
        "headline_action": headline,
        "target_status": target_status,
        "delta_status": delta_status,
        "decision_state": headline,
        "mirror_rows": mirror_rows,
        "meta": ["READ ONLY", "TARGET ≠ ORDER", "RISK NOT APPLIED"],
        "evidence": primary or "—",
        "why_not": primary,
        "disclaimer": "DELTA ≠ EXECUTION · RISKGATE NOT APPLIED · P3-R3 HOLD",
        "tone": "defensive" if candidate.get("event_action") == "RISK_OFF" else "neutral",
        "decision_trace_summary": trace.get("winner"),
    }


def _build_right_evidence(
    candidate: Dict[str, Any],
    trace: Dict[str, Any],
    *,
    account_truth: Dict[str, str],
    account_version: Optional[str],
) -> Dict[str, Any]:
    cur = candidate.get("current_state") or {}
    tgt = candidate.get("target_state") or {}
    delta = candidate.get("delta_proposal") or {}
    cluster = candidate.get("crypto_beta_cluster") or {}

    return {
        "title": "PORTFOLIO DECISION",
        "final_view": {
            "decision_state": candidate.get("runtime_kind"),
            "target_status": tgt.get("status"),
            "delta_status": delta.get("status"),
            "primary_blocker": _primary_blocker(candidate.get("blockers") or []),
            "decision_key": candidate.get("decision_key"),
            "as_of": candidate.get("as_of"),
            "idempotent": candidate.get("idempotent", False),
        },
        "current": {
            "btc": cur.get("btc"),
            "eth": cur.get("eth"),
            "usdt": cur.get("usdt"),
            "btc_overlay": cur.get("btc_overlay"),
            "eth_overlay": cur.get("eth_overlay"),
            "truth_status": cur.get("status"),
            "account_version": account_version,
        },
        "target_candidate": {
            "btc": tgt.get("btc"),
            "eth": tgt.get("eth"),
            "usdt": tgt.get("usdt"),
            "btc_overlay": tgt.get("btc_overlay"),
            "eth_overlay": tgt.get("eth_overlay"),
            "event_increment": tgt.get("event_increment"),
            "status": tgt.get("status"),
        },
        "delta_proposal": {
            "btc": delta.get("btc"),
            "eth": delta.get("eth"),
            "usdt": delta.get("usdt"),
            "btc_overlay": delta.get("btc_overlay"),
            "eth_overlay": delta.get("eth_overlay"),
            "event_increment": delta.get("event_increment"),
            "status": delta.get("status"),
        },
        "why": {
            "decision_trace": trace.get("stages") or [],
            "trace_winner": trace.get("winner"),
            "crypto_beta_cluster": {
                "btc_overlay_request": cluster.get("btc_request"),
                "eth_overlay_request": cluster.get("eth_request"),
                "combined_state": "CLUSTERED" if (cluster.get("total_request") or 0) > 0 else "NONE",
                "independent_full_budgets": "NOT ALLOWED",
                "cluster_cap": cluster.get("cluster_cap"),
            },
            "event_increment": {
                "base_trend_risk": "ELIGIBLE" if (cluster.get("total_request") or 0) > 0 else "NONE",
                "event_increment_request": candidate.get("event_increment_request"),
                "final_risk_amount": "NOT DECIDED",
            },
            "reasons": candidate.get("reasons") or [],
            "blockers": candidate.get("blockers") or [],
            "spot_action": candidate.get("spot_action"),
            "btc_overlay_action": candidate.get("btc_overlay_action"),
            "event_action": candidate.get("event_action"),
        },
        "authority": {
            "riskgate": "NOT APPLIED",
            "execution": "DENIED",
            "submit_allowed": False,
            "target_not_order": True,
            "delta_not_execution": True,
        },
    }


def build_decision_observatory_snapshot(
    *,
    trend_quant: Dict[str, Any],
    eth_btc: Dict[str, Any],
    event_bundle: Dict[str, Any],
    exchange: Dict[str, Any],
    account_meta: Optional[Dict[str, Any]] = None,
    authoritative_current: Optional[Dict[str, Any]] = None,
    previous_decision: Optional[Dict[str, Any]] = None,
    account_version: Optional[str] = None,
    position_version: Optional[str] = None,
    fixture_event_pipeline: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Project P3-R1 candidate into observatory.decision bundle."""
    if fixture_event_pipeline and not event_bundle.get("items"):
        from aurora.event_observatory import build_event_observatory_snapshot
        event_bundle = build_event_observatory_snapshot(
            official_sources_connected=True,
            fixture_pipeline=fixture_event_pipeline,
            btc_trend=trend_quant.get("btc"),
            eth_trend=trend_quant.get("eth"),
        )

    account_truth = _account_truth_from_exchange(exchange, account_meta or {})
    if authoritative_current:
        account_truth = {"account": "KNOWN", "position": "KNOWN", "protection": "KNOWN"}
    current = _authoritative_current(exchange, account_truth, override=authoritative_current)

    trend_btc = normalize_trend_decision_input(trend_quant, asset="btc")
    trend_eth = normalize_trend_decision_input(trend_quant, asset="eth")
    value_in = normalize_value_decision_input(eth_btc)
    event_in = normalize_event_decision_input(event_bundle)

    if current is None:
        current = {"status": "UNKNOWN"}

    norm = build_normalized_decision_input(
        trend_btc=trend_btc,
        trend_eth=trend_eth,
        value_input=value_in,
        event_input=event_in,
        account_truth=account_truth,
        current_state=current,
        account_version=account_version or (account_meta or {}).get("version"),
        position_version=position_version,
        previous_decision=previous_decision,
        as_of=event_bundle.get("as_of") or _now_iso(),
    )

    candidate = evaluate_decision(norm, default_decision_policy())
    trace = _build_decision_trace(candidate)
    left_card = _build_left_card(candidate, trace)
    right = _build_right_evidence(
        candidate,
        trace,
        account_truth=account_truth,
        account_version=account_version,
    )

    return {
        "capability": CAP_DECISION,
        "status": "ok",
        "as_of": candidate.get("as_of"),
        "live": False,
        "submit_allowed": False,
        "decision_key": candidate.get("decision_key"),
        "candidate": candidate,
        "left_card": left_card,
        "right_evidence": right,
        "decision_trace": trace,
        "disclaimer": left_card.get("disclaimer"),
        "target_status": left_card.get("target_status"),
        "delta_status": left_card.get("delta_status"),
        "account_truth": account_truth,
    }
