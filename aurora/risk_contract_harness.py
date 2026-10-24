"""P3-R3.0 Risk Contract Harness — pure contract evaluator (NOT legacy RiskGate).

CONSTITUTION:
  RISK MONOTONICITY — Risk output may KEEP / REDUCE / BLOCK; never BOOST / INCREASE.

FROZEN:
  PortfolioDecisionCandidate + RiskTruthSnapshot + RiskPolicySnapshot
        ↓
  evaluate_risk()
        ↓
  RiskAdjudicatedPortfolioPlan

  submit_allowed = False always
  No exchange / execution / portfolio_brain_v2 / risk_gate imports
"""
from __future__ import annotations

import ast
import hashlib
import json
import math
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

HARNESS_KIND = "P3_R3_RISK_CONTRACT_HARNESS"
PARAMETER_STATUS = "PROVISIONAL_E3_PARAM"

FORBIDDEN_IMPORT_FRAGMENTS = frozenset({
    "portfolio_brain_v2",
    "risk_gate",
    "risk_kernel",
    "binance_exchange",
    "armed_runtime",
    "execution",
    "binance",
})

FORBIDDEN_OUTPUT_KEYS = frozenset({
    "order_id",
    "client_order_id",
    "exchange_qty",
    "submit",
    "execute",
    "close_position",
    "place_order",
})

RISK_STATES = frozenset({
    "PASS",
    "REDUCED",
    "BLOCK_NEW_RISK",
    "DEFENSIVE_ONLY",
    "UNKNOWN",
})

DEFAULT_RISK_POLICY: Dict[str, Any] = {
    "policy_version": "p3-r3-v1",
    "policy_hash": "p3-r3-policy-v1",
    "parameter_status": PARAMETER_STATUS,
    "per_trade_loss_budget": 0.0075,
    "cluster_loss_budget": 0.0100,
    "overlay_pool_loss_budget": 0.0100,
    "event_increment_budget": 0.0030,
    "managed_gross_exposure_max": 1.0,
    "funding_cost_budget": 0.0020,
    "drawdown_budget": 0.1500,
    "stress_policy": {"enabled": True, "haircut": 0.85},
    "sizing_policy": {"min_unit_loss": 1e-9, "qty_step": 0.001},
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_risk_policy() -> Dict[str, Any]:
    return deepcopy(DEFAULT_RISK_POLICY)


def policy_hash(policy: Dict[str, Any]) -> str:
    return policy.get("policy_hash") or hashlib.sha256(
        json.dumps(policy, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]


def scan_forbidden_imports(module_path: str) -> List[str]:
    with open(module_path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    hits: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                hits.extend(_match_banned(alias.name))
        elif isinstance(node, ast.ImportFrom) and node.module:
            hits.extend(_match_banned(node.module))
    return sorted(set(hits))


def _match_banned(module: str) -> List[str]:
    mod = (module or "").lower()
    return [module for frag in FORBIDDEN_IMPORT_FRAGMENTS if frag in mod]


def build_risk_plan_key(
    *,
    decision_key: str,
    account_version: Optional[str] = None,
    position_version: Optional[str] = None,
    protection_version: Optional[str] = None,
    truth_as_of: Optional[str] = None,
    policy_hash_value: str,
) -> str:
    payload = {
        "decision_key": decision_key or "none",
        "account_version": account_version or "0",
        "position_version": position_version or "0",
        "protection_version": protection_version or "0",
        "truth_as_of": truth_as_of or "0",
        "policy_hash": policy_hash_value,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def _is_unknown(val: Any) -> bool:
    if val is None:
        return True
    if isinstance(val, str) and val.upper() in ("UNKNOWN", "UNAVAILABLE", ""):
        return True
    return False


def _mix_copy(state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    st = state or {}
    return {
        "status": st.get("status") or "UNKNOWN",
        "btc": st.get("btc"),
        "eth": st.get("eth"),
        "usdt": st.get("usdt"),
        "btc_overlay": st.get("btc_overlay"),
        "eth_overlay": st.get("eth_overlay"),
        "event_increment": st.get("event_increment"),
    }


def _delta_copy(delta: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    d = delta or {}
    return {
        "status": d.get("status") or "UNAVAILABLE",
        "btc": d.get("btc"),
        "eth": d.get("eth"),
        "usdt": d.get("usdt"),
        "btc_overlay": d.get("btc_overlay"),
        "eth_overlay": d.get("eth_overlay"),
        "event_increment": d.get("event_increment"),
    }


def _num(val: Any, default: Optional[float] = None) -> Optional[float]:
    if val is None or _is_unknown(val):
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _min_nonneg(requested: float, cap: Optional[float]) -> float:
    """Monotonic cap — never above request, never below zero for new-risk slots."""
    if cap is None:
        return 0.0
    return max(0.0, min(float(requested), float(cap)))


def _is_defensive_candidate(candidate: Dict[str, Any]) -> bool:
    if candidate.get("event_action") == "RISK_OFF":
        return True
    if candidate.get("btc_overlay_action") in ("CLOSE_OVERLAY",):
        return True
    if candidate.get("spot_action") in ("REDUCE_OR_CLOSE",):
        return True
    if candidate.get("eth_overlay_action") == "CLOSE_OVERLAY":
        return True
    return bool(candidate.get("thesis_invalidated") or candidate.get("close_condition"))


def _is_new_risk_action(candidate: Dict[str, Any]) -> bool:
    if candidate.get("btc_overlay_action") == "INCREASE_CANDIDATE":
        return True
    if candidate.get("eth_overlay_action") == "INCREASE_CANDIDATE":
        return True
    if candidate.get("spot_action") in ("REALLOCATE_ETH_ELIGIBLE", "WATCH_ETH"):
        return True
    if candidate.get("event_increment_request") == "ELIGIBLE":
        return True
    if candidate.get("event_action") == "INCREMENT_REQUEST":
        return True
    cluster = candidate.get("crypto_beta_cluster") or {}
    return float(cluster.get("total_request") or 0) > 0


def _policy_budget_or_block(
    policy: Dict[str, Any],
    key: str,
    blockers: List[str],
) -> Optional[float]:
    val = policy.get(key)
    if val is None:
        blockers.append(f"RISK_POLICY_NULL:{key}")
        return None
    return float(val)


def _unit_loss_at_stop(sizing: Dict[str, Any]) -> Optional[float]:
    entry = _num(sizing.get("entry_estimate"))
    stop = _num(sizing.get("stop_price"))
    if entry is None or stop is None:
        return None
    slip = _num(sizing.get("adverse_slippage"), 0.0) or 0.0
    fees = _num(sizing.get("fees"), 0.0) or 0.0
    funding = _num(sizing.get("stressed_funding"), 0.0) or 0.0
    return abs(entry - stop) + slip + fees + funding


def _floor_to_step(qty: float, step: float) -> float:
    if step <= 0:
        return qty
    return math.floor(qty / step) * step


def _qty_from_risk_at_stop(
    *,
    allocated_budget: float,
    unit_loss: float,
    q_target: float,
    q_exposure: Optional[float],
    q_margin: Optional[float],
    q_stress: Optional[float],
    qty_step: float,
) -> float:
    if unit_loss <= 0:
        return 0.0
    q_risk = allocated_budget / unit_loss
    candidates = [q_target, q_risk]
    if q_exposure is not None:
        candidates.append(q_exposure)
    if q_margin is not None:
        candidates.append(q_margin)
    if q_stress is not None:
        candidates.append(q_stress)
    q_final = min(candidates)
    return _floor_to_step(max(0.0, q_final), qty_step)


def extract_new_risk_vectors(plan: Dict[str, Any]) -> Tuple[Dict[str, float], Dict[str, float]]:
    """Return (requested, allowed) non-negative new-risk vectors for monotonicity checks."""
    req_cluster = plan.get("crypto_beta_cluster") or {}
    req_event = plan.get("event_increment") or {}
    req_loss = plan.get("loss_budget") or {}
    requested = {
        "cluster_total": float((req_cluster.get("requested") or {}).get("total") or 0),
        "btc_overlay": float((req_cluster.get("requested") or {}).get("btc") or 0),
        "eth_overlay": float((req_cluster.get("requested") or {}).get("eth") or 0),
        "event_increment": float(req_event.get("requested") or 0),
        "loss_budget": float(req_loss.get("requested") or 0),
        "gross_exposure": float(plan.get("_gross_exposure_requested") or 0),
    }
    allowed = {
        "cluster_total": float((req_cluster.get("allowed") or {}).get("total") or 0),
        "btc_overlay": float((req_cluster.get("allowed") or {}).get("btc") or 0),
        "eth_overlay": float((req_cluster.get("allowed") or {}).get("eth") or 0),
        "event_increment": float(req_event.get("allowed") or 0),
        "loss_budget": float(req_loss.get("allowed") or 0),
        "gross_exposure": float(plan.get("_gross_exposure_allowed") or 0),
    }
    return requested, allowed


def assert_risk_monotonicity(plan: Dict[str, Any]) -> List[str]:
    """R3-16 property — allowed new risk must never exceed requested."""
    violations: List[str] = []
    requested, allowed = extract_new_risk_vectors(plan)
    for key, req_val in requested.items():
        alw = allowed.get(key, 0.0)
        if alw > req_val + 1e-9:
            violations.append(f"{key}: allowed={alw} > requested={req_val}")
    return violations


def evaluate_risk(
    candidate: Dict[str, Any],
    risk_truth: Dict[str, Any],
    risk_policy: Optional[Dict[str, Any]] = None,
    *,
    sizing_context: Optional[Dict[str, Any]] = None,
    previous_plan: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Pure risk adjudication contract — reduces/blocks only, never inflates Brain request."""
    policy = risk_policy or default_risk_policy()
    pol_hash = policy_hash(policy)
    as_of = risk_truth.get("as_of") or candidate.get("as_of") or _now_iso()

    blockers: List[str] = []
    reasons: List[str] = []
    constraints: List[str] = []

    account = risk_truth.get("account_truth") or {}
    position = risk_truth.get("position_truth") or {}
    protection = risk_truth.get("protection_truth") or {}
    portfolio_risk = risk_truth.get("portfolio_risk_truth") or {}
    market_cost = risk_truth.get("market_cost_truth") or {}
    governance = risk_truth.get("governance") or {}

    defensive = _is_defensive_candidate(candidate)
    new_risk = _is_new_risk_action(candidate)
    kill_active = (governance.get("kill") or "").upper() in ("ACTIVE", "INCIDENT_LOCKED")
    open_blocked = False
    open_gate_issues: List[str] = []

    # --- Truth gates (fail-closed, no zero fallbacks) ---
    btc_nav = account.get("btc_nav")
    if _is_unknown(btc_nav):
        blockers.append("BTC_NAV_UNKNOWN")
        open_blocked = True
        reasons.append("R3: BTC NAV unknown — no fabricated budget")

    drawdown = portfolio_risk.get("drawdown")
    if _is_unknown(drawdown):
        blockers.append("DRAWDOWN_TRUTH_UNKNOWN")
        open_blocked = True
        reasons.append("R3: drawdown truth unknown — block new risk")

    if _is_unknown(account.get("status")):
        blockers.append("ACCOUNT_TRUTH_UNKNOWN")
        open_blocked = True

    funding = market_cost.get("btc_funding")
    funding_unknown = _is_unknown(funding)
    spread_stale = (market_cost.get("freshness") or "").lower() in ("stale", "unknown")

    stop_plan = (protection.get("stop_plan_state") or "UNKNOWN").upper()
    exchange_prot = (protection.get("active_protection_state") or "UNKNOWN").upper()

    if stop_plan != "AUTHORITATIVE" and new_risk and not defensive:
        blockers.append("STOP_PLAN_NOT_AUTHORITATIVE")
        open_blocked = True
        reasons.append("R3: PROPOSED/UNKNOWN stop plan cannot authorize new overlay risk")

    if funding_unknown:
        open_gate_issues.append("FUNDING_TRUTH_UNKNOWN")
        if new_risk and not defensive:
            blockers.append("FUNDING_TRUTH_UNKNOWN")
            open_blocked = True
            reasons.append("R3: funding UNKNOWN blocks derivative OPEN/ADD")

    if spread_stale:
        open_gate_issues.append("MARKET_COST_STALE")
        if new_risk and not defensive:
            blockers.append("MARKET_COST_STALE")
            open_blocked = True
            reasons.append("R3: stale spread/cost — block new overlay (not treated as zero)")

    if kill_active and new_risk:
        blockers.append("KILL_ACTIVE")
        open_blocked = True
        reasons.append("R3: KILL ACTIVE — new risk blocked; defensive preserved")

    per_trade = _policy_budget_or_block(policy, "per_trade_loss_budget", blockers)
    cluster_budget = _policy_budget_or_block(policy, "cluster_loss_budget", blockers)
    overlay_pool = _policy_budget_or_block(policy, "overlay_pool_loss_budget", blockers)
    event_budget = _policy_budget_or_block(policy, "event_increment_budget", blockers)
    gross_max = _policy_budget_or_block(policy, "managed_gross_exposure_max", blockers)

    policy_incomplete = any(k.startswith("RISK_POLICY_NULL:") for k in blockers)

    # --- Requested from Brain (never mutate upward) ---
    cluster_req = candidate.get("crypto_beta_cluster") or {}
    req_btc_o = float(cluster_req.get("btc_request") or 0)
    req_eth_o = float(cluster_req.get("eth_request") or 0)
    req_cluster_total = float(cluster_req.get("total_request") or 0)

    cur = _mix_copy(candidate.get("current_state"))
    tgt = _mix_copy(candidate.get("target_state"))
    req_delta = _delta_copy(candidate.get("delta_proposal"))

    req_event_inc = float(tgt.get("event_increment") or 0) - float(cur.get("event_increment") or 0)
    if req_event_inc < 0:
        req_event_inc = 0.0
    if candidate.get("event_increment_request") != "ELIGIBLE":
        req_event_inc = max(0.0, min(req_event_inc, 0.0))

    req_loss = req_cluster_total + req_event_inc

    # --- Allowed caps (monotonic min) ---
    if policy_incomplete or open_blocked:
        allowed_cluster_total = 0.0 if (open_blocked and not defensive) else None
        allowed_btc_o = 0.0 if (open_blocked and not defensive) else None
        allowed_eth_o = 0.0 if (open_blocked and not defensive) else None
        allowed_event = 0.0 if (open_blocked and not defensive) else None
    else:
        allowed_cluster_total = cluster_budget
        allowed_btc_o = min(req_btc_o, per_trade or 0, overlay_pool or 0)
        allowed_eth_o = min(req_eth_o, per_trade or 0, overlay_pool or 0)
        if req_btc_o > 0 and req_eth_o > 0:
            # CRYPTO_BETA_CLUSTER joint cap
            pool = min(cluster_budget or 0, overlay_pool or 0)
            btc_share = 0.70
            eth_share = 0.30
            cap_btc = min(req_btc_o, per_trade or 0, pool * btc_share)
            cap_eth = min(req_eth_o, per_trade or 0, pool * eth_share)
            if cap_btc + cap_eth > pool:
                allowed_btc_o = cap_btc
                allowed_eth_o = min(cap_eth, max(0.0, pool - cap_btc))
            else:
                allowed_btc_o, allowed_eth_o = cap_btc, cap_eth
            allowed_cluster_total = allowed_btc_o + allowed_eth_o
            reasons.append("R3: CRYPTO_BETA_CLUSTER joint adjudication")
        else:
            allowed_cluster_total = min(req_cluster_total, cluster_budget or 0, overlay_pool or 0)
            allowed_btc_o = _min_nonneg(req_btc_o, min(per_trade or 0, overlay_pool or 0))
            allowed_eth_o = _min_nonneg(req_eth_o, min(per_trade or 0, overlay_pool or 0))

        remaining_pool = max(0.0, (cluster_budget or 0) - (allowed_cluster_total or 0))
        event_cap = min(event_budget or 0, remaining_pool)
        allowed_event = _min_nonneg(req_event_inc, event_cap)
        if req_event_inc > 0 and allowed_event < req_event_inc:
            reasons.append("R3: event increment consumes remaining unified budget only")

    if open_blocked and not defensive:
        allowed_cluster_total = 0.0
        allowed_btc_o = 0.0
        allowed_eth_o = 0.0
        allowed_event = 0.0

    if allowed_cluster_total is None:
        allowed_cluster_total = 0.0
    if allowed_btc_o is None:
        allowed_btc_o = 0.0
    if allowed_eth_o is None:
        allowed_eth_o = 0.0
    if allowed_event is None:
        allowed_event = 0.0

    # Hard monotonic clamp
    allowed_btc_o = _min_nonneg(req_btc_o, allowed_btc_o)
    allowed_eth_o = _min_nonneg(req_eth_o, allowed_eth_o)
    allowed_cluster_total = _min_nonneg(req_cluster_total, min(allowed_cluster_total, allowed_btc_o + allowed_eth_o))
    allowed_event = _min_nonneg(req_event_inc, allowed_event)
    allowed_loss = _min_nonneg(req_loss, allowed_cluster_total + allowed_event)

    # Risk-at-stop sizing (R3-11)
    sizing = sizing_context or {}
    qty_step = float((policy.get("sizing_policy") or {}).get("qty_step") or 0.001)
    unit_loss = _unit_loss_at_stop(sizing)
    q_target = _num(sizing.get("q_target"), 0.0) or 0.0
    q_allowed = None
    if unit_loss is not None and q_target > 0:
        q_allowed = _qty_from_risk_at_stop(
            allocated_budget=allowed_loss,
            unit_loss=unit_loss,
            q_target=q_target,
            q_exposure=_num(sizing.get("q_exposure")),
            q_margin=_num(sizing.get("q_margin")),
            q_stress=_num(sizing.get("q_stress")),
            qty_step=qty_step,
        )
        if q_allowed < q_target - 1e-9:
            reasons.append("R3: q_allowed reduced by risk-at-stop (unit_loss includes fee/slip/funding)")

    gross_requested = req_cluster_total + req_event_inc
    gross_allowed = allowed_cluster_total + allowed_event
    if gross_max is not None:
        gross_allowed = _min_nonneg(gross_requested, min(gross_allowed, gross_max))

    # --- Risk-adjusted target (never above Brain target on risk dimensions) ---
    adj_tgt = deepcopy(tgt)
    adj_tgt["btc_overlay"] = min(float(tgt.get("btc_overlay") or 0), float(cur.get("btc_overlay") or 0) + allowed_btc_o)
    adj_tgt["eth_overlay"] = min(float(tgt.get("eth_overlay") or 0), float(cur.get("eth_overlay") or 0) + allowed_eth_o)
    adj_tgt["event_increment"] = min(float(tgt.get("event_increment") or 0), float(cur.get("event_increment") or 0) + allowed_event)

    # --- Risk-adjusted delta ---
    adj_delta = deepcopy(req_delta)
    position_unknown = _is_unknown(position.get("status"))
    defensive_preserved = defensive and (candidate.get("reduce_allowed") or candidate.get("close_allowed"))

    if position_unknown and defensive_preserved:
        adj_delta["status"] = "UNAVAILABLE"
        blockers.append("POSITION_TRUTH_UNKNOWN_DEFENSIVE_DELTA_UNAVAILABLE")
        reasons.append("R3: defensive intent preserved; exact executable delta unavailable")
    elif adj_delta.get("status") == "AVAILABLE" and cur.get("status") == "KNOWN":
        adj_delta["btc_overlay"] = (adj_tgt.get("btc_overlay") or 0) - (cur.get("btc_overlay") or 0)
        adj_delta["eth_overlay"] = (adj_tgt.get("eth_overlay") or 0) - (cur.get("eth_overlay") or 0)
        adj_delta["event_increment"] = (adj_tgt.get("event_increment") or 0) - (cur.get("event_increment") or 0)
        if open_blocked and not defensive:
            adj_delta["btc_overlay"] = min(0.0, float(adj_delta.get("btc_overlay") or 0))
            adj_delta["eth_overlay"] = min(0.0, float(adj_delta.get("eth_overlay") or 0))
            adj_delta["event_increment"] = min(0.0, float(adj_delta.get("event_increment") or 0))
    elif open_blocked and not defensive:
        adj_delta["status"] = "UNAVAILABLE"

    # --- Risk state ---
    reduced = (
        allowed_cluster_total < req_cluster_total - 1e-9
        or allowed_event < req_event_inc - 1e-9
        or (q_allowed is not None and q_allowed < q_target - 1e-9)
    )
    if policy_incomplete or _is_unknown(btc_nav) or _is_unknown(drawdown):
        risk_state = "UNKNOWN" if policy_incomplete else "BLOCK_NEW_RISK"
    elif kill_active and defensive_preserved:
        risk_state = "DEFENSIVE_ONLY"
    elif (open_blocked or open_gate_issues) and defensive_preserved:
        risk_state = "DEFENSIVE_ONLY"
    elif open_blocked:
        risk_state = "BLOCK_NEW_RISK"
    elif reduced:
        risk_state = "REDUCED"
    else:
        risk_state = "PASS"

    if kill_active:
        constraints.append("NEW_RISK_ALLOWED=FALSE")
        constraints.append("DEFENSIVE_REDUCTION_PRESERVED=TRUE")

    decision_key = candidate.get("decision_key") or "none"
    risk_plan_key = build_risk_plan_key(
        decision_key=decision_key,
        account_version=account.get("version"),
        position_version=position.get("version"),
        protection_version=protection.get("version"),
        truth_as_of=as_of,
        policy_hash_value=pol_hash,
    )

    idempotent = (
        previous_plan is not None
        and previous_plan.get("risk_plan_key") == risk_plan_key
        and previous_plan.get("based_on_decision_key") == decision_key
    )
    if idempotent:
        blockers.append("IDEMPOTENT_RISK_PLAN_KEY")

    cluster_state = "CLUSTERED" if req_btc_o > 0 and req_eth_o > 0 else ("SINGLE" if req_cluster_total > 0 else "NONE")
    if allowed_cluster_total <= 0 and req_cluster_total > 0 and open_blocked:
        cluster_state = "BLOCKED"

    event_state = "ELIGIBLE" if req_event_inc > 0 else "NONE"
    if allowed_event <= 0 and req_event_inc > 0:
        event_state = "BLOCKED" if open_blocked else "REDUCED"

    out: Dict[str, Any] = {
        "runtime_kind": HARNESS_KIND,
        "as_of": as_of,
        "risk_plan_key": risk_plan_key,
        "based_on_decision_key": decision_key,
        "risk_state": risk_state,
        "current_state": cur,
        "requested_target": tgt,
        "risk_adjusted_target": adj_tgt,
        "requested_delta": req_delta,
        "risk_adjusted_delta": adj_delta,
        "crypto_beta_cluster": {
            "requested": {"btc": req_btc_o, "eth": req_eth_o, "total": req_cluster_total},
            "allowed": {"btc": allowed_btc_o, "eth": allowed_eth_o, "total": allowed_cluster_total},
            "state": cluster_state,
        },
        "event_increment": {
            "requested": req_event_inc,
            "allowed": allowed_event,
            "state": event_state,
        },
        "loss_budget": {
            "requested": req_loss,
            "allowed": allowed_loss,
            "status": "REDUCED" if allowed_loss < req_loss - 1e-9 else "PASS",
        },
        "sizing_at_stop": {
            "unit_loss": unit_loss,
            "q_target": q_target,
            "q_allowed": q_allowed,
            "status": "REDUCED" if q_allowed is not None and q_allowed < q_target - 1e-9 else "PASS",
        },
        "protection": {
            "stop_plan_state": stop_plan,
            "exchange_protection_state": exchange_prot,
        },
        "constraints": constraints,
        "blockers": blockers,
        "reasons": reasons,
        "submit_allowed": False,
        "defensive_reduction_preserved": bool(defensive_preserved),
        "new_risk_allowed": not open_blocked and not kill_active and not policy_incomplete,
        "idempotent": idempotent,
        "_gross_exposure_requested": gross_requested,
        "_gross_exposure_allowed": gross_allowed,
    }
    _assert_harness_output(out)
    return out


def _assert_harness_output(out: Dict[str, Any]) -> None:
    if out.get("submit_allowed"):
        raise ValueError("R3 harness: submit_allowed must be False")
    if out.get("risk_state") not in RISK_STATES:
        raise ValueError(f"invalid risk_state: {out.get('risk_state')}")
    blob = json.dumps(out)
    for key in FORBIDDEN_OUTPUT_KEYS:
        if f'"{key}"' in blob:
            raise ValueError(f"R3 harness forbids output key: {key}")
    violations = assert_risk_monotonicity(out)
    if violations:
        raise ValueError(f"RISK MONOTONICITY violated: {violations}")
