"""P3-R1 Decision Brain Core — read-only portfolio decision candidate.

PURE INPUT → PURE DECISION. No observatory. No exchange. No RiskGate. No execution.

FROZEN:
  Consumes NormalizedDecisionInput only (via entry_gate normalizers upstream)
  All allocation percentages from DecisionPolicySnapshot (PROVISIONAL_E3_PARAM)
  CURRENT never fabricated — Account UNKNOWN → delta UNAVAILABLE
  TARGET may be CANDIDATE without authoritative CURRENT
  submit_allowed = False always
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from aurora.decision_brain_entry_gate import (
    CONTRACT_HASH_A,
    CONTRACT_HASH_B,
    CONTRACT_HASH_C,
    FORBIDDEN_OUTPUT_EXTENDED,
    audit_unknown_cross_engine,
    build_brain_decision_key,
)

RUNTIME_KIND = "P3_DECISION_BRAIN_READ_ONLY"
STRATEGY_HASH_DEFAULT = "strategy-v1"

FORBIDDEN_IMPORT_MODULES = frozenset({
    "observatory_snapshots",
    "dashboard_feed",
    "portfolio_brain_v2",
    "binance",
    "risk_gate",
    "execution",
})

# PROVISIONAL_E3_PARAM — mechanism frozen; numeric bands not Alpha truth
DEFAULT_DECISION_POLICY: Dict[str, Any] = {
    "policy_version": "p3-r1-v1",
    "policy_hash": "p3-r1-policy-v1",
    "parameter_status": "PROVISIONAL_E3_PARAM",
    "btc_default_band": {"btc": 80.0, "eth": 10.0, "usdt": 10.0},
    "eth_candidate_band": {"btc": 75.0, "eth": 15.0, "usdt": 10.0},
    "eth_confirmed_band": {"btc": 70.0, "eth": 20.0, "usdt": 10.0},
    "trend_overlay_caps": {
        "per_asset_max": 0.0075,
        "parameter_status": "PROVISIONAL_E3_PARAM",
    },
    "crypto_beta_cluster_cap": {
        "total": 0.0100,
        "btc_share": 0.70,
        "eth_share": 0.30,
        "parameter_status": "PROVISIONAL_E3_PARAM",
    },
    "event_increment_cap": 0.0030,
    "trend_min_level_overlay": 3,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _level_num(level: Optional[str]) -> int:
    if not level:
        return 0
    for ch in str(level):
        if ch.isdigit():
            return int(ch)
    return 0


def default_decision_policy() -> Dict[str, Any]:
    return deepcopy(DEFAULT_DECISION_POLICY)


def policy_hash(policy: Dict[str, Any]) -> str:
    return policy.get("policy_hash") or hashlib.sha256(
        json.dumps(policy, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]


def _mix_state(
    *,
    status: str,
    btc: Optional[float] = None,
    eth: Optional[float] = None,
    usdt: Optional[float] = None,
    btc_overlay: Optional[float] = None,
    eth_overlay: Optional[float] = None,
    event_increment: Optional[float] = None,
) -> Dict[str, Any]:
    return {
        "status": status,
        "btc": btc,
        "eth": eth,
        "usdt": usdt,
        "btc_overlay": btc_overlay,
        "eth_overlay": eth_overlay,
        "event_increment": event_increment,
    }


def _delta_from(current: Dict[str, Any], target: Dict[str, Any]) -> Dict[str, Any]:
    def d(k: str) -> Optional[float]:
        c, t = current.get(k), target.get(k)
        if c is None or t is None:
            return None
        return round(float(t) - float(c), 6)

    return {
        "status": "AVAILABLE",
        "btc": d("btc"),
        "eth": d("eth"),
        "usdt": d("usdt"),
        "btc_overlay": d("btc_overlay"),
        "eth_overlay": d("eth_overlay"),
        "event_increment": d("event_increment"),
    }


def _p0_truth_gate(account_truth: Dict[str, Any]) -> Tuple[List[str], bool, bool]:
    blockers: List[str] = []
    account_unknown = (account_truth.get("account") or "UNKNOWN") == "UNKNOWN"
    position_unknown = (account_truth.get("position") or "UNKNOWN") == "UNKNOWN"
    protection_unknown = (account_truth.get("protection") or "UNKNOWN") == "UNKNOWN"
    if account_unknown:
        blockers.append("ACCOUNT_TRUTH_UNKNOWN")
    if position_unknown:
        blockers.append("POSITION_TRUTH_UNKNOWN")
    if protection_unknown:
        blockers.append("PROTECTION_TRUTH_UNKNOWN")
    open_new_risk = not (account_unknown or position_unknown or protection_unknown)
    return blockers, open_new_risk, account_unknown


def _cluster_overlay_risk(
    btc_level: str,
    eth_level: str,
    policy: Dict[str, Any],
) -> Tuple[float, float, float]:
    cap_cfg = policy["crypto_beta_cluster_cap"]
    per_max = policy["trend_overlay_caps"]["per_asset_max"]
    cap = float(cap_cfg["total"])
    bn = _level_num(btc_level)
    en = _level_num(eth_level)
    min_lvl = int(policy.get("trend_min_level_overlay") or 3)
    if bn < min_lvl and en < min_lvl:
        return 0.0, 0.0, 0.0
    if bn >= min_lvl and en >= min_lvl:
        btc_r = min(per_max, cap * float(cap_cfg["btc_share"]))
        eth_r = min(per_max, cap * float(cap_cfg["eth_share"]))
        return btc_r, eth_r, btc_r + eth_r
    if bn >= min_lvl:
        return min(per_max, cap), 0.0, min(per_max, cap)
    return 0.0, min(per_max, cap), min(per_max, cap)


def _spot_band(value_input: Dict[str, Any], policy: Dict[str, Any]) -> Optional[Dict[str, float]]:
    signal = value_input.get("allocation_signal") or "NO_REALLOCATION"
    state = value_input.get("allocation_state") or "BTC_DEFAULT"
    if signal == "INCREASE_ETH_ELIGIBLE" or state == "ETH_CONFIRMED":
        return dict(policy["eth_confirmed_band"])
    if state == "ETH_CANDIDATE" or signal == "WATCH_ETH":
        return dict(policy["eth_candidate_band"])
    return dict(policy["btc_default_band"])


def evaluate_decision(
    normalized_input: Dict[str, Any],
    decision_policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """P3-R1 sole entry — NormalizedDecisionInput + DecisionPolicySnapshot → candidate."""
    policy = decision_policy or default_decision_policy()
    inp = normalized_input
    as_of = inp.get("as_of") or _now_iso()

    trend_btc = inp.get("trend_btc") or {}
    trend_eth = inp.get("trend_eth") or {}
    value_in = inp.get("value_input") or {}
    event_in = inp.get("event_input") or {}
    account_truth = inp.get("account_truth") or {
        "account": "UNKNOWN", "position": "UNKNOWN", "protection": "UNKNOWN",
    }
    rearm = inp.get("rearm") or {}
    risk_ctx = inp.get("risk_context") or {}

    reasons: List[str] = []
    blockers: List[str] = list(inp.get("blockers") or [])

    # --- P0 TRUTH GATE ---
    p0_blockers, open_new_risk, account_unknown = _p0_truth_gate(account_truth)
    blockers.extend(p0_blockers)
    if p0_blockers:
        reasons.append("P0: truth incomplete — block new risk")

    cross = audit_unknown_cross_engine(trend_btc, value_in, event_in)
    blockers.extend(cross)
    if cross:
        open_new_risk = False

    # --- CURRENT (never fabricated) ---
    cur_in = inp.get("current_state") or {}
    current_status = cur_in.get("status") or ("UNKNOWN" if account_unknown else "KNOWN")
    if account_unknown:
        current_status = "UNKNOWN"
    current = _mix_state(
        status=current_status,
        btc=cur_in.get("btc") if current_status == "KNOWN" else None,
        eth=cur_in.get("eth") if current_status == "KNOWN" else None,
        usdt=cur_in.get("usdt") if current_status == "KNOWN" else None,
        btc_overlay=cur_in.get("btc_overlay") if current_status == "KNOWN" else None,
        eth_overlay=cur_in.get("eth_overlay") if current_status == "KNOWN" else None,
        event_increment=cur_in.get("event_increment") if current_status == "KNOWN" else None,
    )

    # --- P2 DEFENSIVE OVERRIDE (wins over enhancement) ---
    thesis_invalid = bool(inp.get("thesis_invalidated") or inp.get("close_condition"))
    risk_off = event_in.get("boost_eligibility") == "RISK_OFF_ELIGIBLE"
    defensive = thesis_invalid or risk_off

    spot_action = "NO_CHANGE"
    btc_overlay_action = "HOLD"
    eth_overlay_action = "HOLD"
    event_action = "NONE"
    event_increment_request = "NONE"

    target_spot = _spot_band(value_in, policy) if not defensive else None
    target_btc_o = float(current.get("btc_overlay") or 0)
    target_eth_o = float(current.get("eth_overlay") or 0)
    target_event_inc = float(current.get("event_increment") or 0)

    if defensive:
        reasons.append("P2: defensive override active")
        if thesis_invalid:
            btc_overlay_action = "CLOSE_OVERLAY"
            eth_overlay_action = "CLOSE_OVERLAY"
            target_btc_o = 0.0
            target_eth_o = 0.0
            spot_action = "REDUCE_OR_CLOSE"
            reasons.append("P2: thesis invalidation — reduce/close candidate survives OPEN block")
        if risk_off:
            event_action = "RISK_OFF"
            event_increment_request = "REMOVE"
            target_event_inc = 0.0
            reasons.append("P2: RISK_OFF wins over Event Boost — no short authority")
    else:
        # --- P3 SPOT ALLOCATION ---
        eth_lvl = _level_num(trend_eth.get("trend_level"))
        signal = value_in.get("allocation_signal") or "NO_REALLOCATION"
        if "VALUE_TRUTH_UNKNOWN" in (value_in.get("blockers") or []):
            spot_action = "NO_REALLOCATION"
            reasons.append("P3: value truth unknown — no spot change")
        elif signal == "INCREASE_ETH_ELIGIBLE" and eth_lvl >= 3 and open_new_risk:
            spot_action = "REALLOCATE_ETH_ELIGIBLE"
            reasons.append("P3: ETH confirmed band candidate from policy")
        elif signal == "WATCH_ETH" or value_in.get("allocation_state") == "ETH_CANDIDATE":
            spot_action = "WATCH_ETH"
            target_spot = dict(policy["eth_candidate_band"])
            reasons.append("P3: watch ETH — no confirmed realloc")
        else:
            spot_action = "NO_CHANGE"
            target_spot = dict(policy["btc_default_band"])

        # --- P4 TREND OVERLAY (CRYPTO_BETA_CLUSTER) ---
        btc_lvl = trend_btc.get("trend_level", "L0/5")
        eth_lvl_s = trend_eth.get("trend_level", "L0/5")
        btc_or, eth_or, cluster_total = _cluster_overlay_risk(btc_lvl, eth_lvl_s, policy)
        if open_new_risk and (btc_or > 0 or eth_or > 0):
            target_btc_o = btc_or
            target_eth_o = eth_or
            btc_overlay_action = "INCREASE_CANDIDATE"
            eth_overlay_action = "INCREASE_CANDIDATE" if eth_or > 0 else "HOLD"
            reasons.append(
                f"P4: CRYPTO_BETA_CLUSTER btc={btc_or:.4f} eth={eth_or:.4f} "
                f"total={cluster_total:.4f}"
            )
        elif not open_new_risk:
            btc_overlay_action = "BLOCKED"
            eth_overlay_action = "BLOCKED"

        # --- P5 EVENT INCREMENT (incremental only) ---
        ev_connected = event_in.get("observation_state") != "SOURCE_NOT_CONNECTED"
        ev_boost = event_in.get("boost_eligibility") == "EVENT_BOOST_ELIGIBLE"
        if not ev_connected:
            reasons.append("P5: event NOT_CONNECTED — increment none")
        elif event_in.get("retracted"):
            event_action = "REMOVED"
            target_event_inc = 0.0
        elif ev_boost and open_new_risk and _level_num(btc_lvl) >= int(policy.get("trend_min_level_overlay") or 3):
            inc_cap = float(policy.get("event_increment_cap") or 0)
            remaining = max(0.0, float(policy["crypto_beta_cluster_cap"]["total"]) - cluster_total)
            inc = min(inc_cap, remaining)
            target_event_inc = inc
            event_action = "INCREMENT_REQUEST"
            event_increment_request = "ELIGIBLE"
            reasons.append(f"P5: incremental event request {inc:.4f} (not double-counted with base {cluster_total:.4f})")
        else:
            event_action = "NONE"
            target_event_inc = 0.0

    # Risk-off on multi-event: if primary is risk_off, already handled in defensive
    if event_in.get("observation_state") == "SOURCE_NOT_CONNECTED":
        event_action = "NONE" if event_action != "RISK_OFF" else event_action
        event_increment_request = "NONE"

    # --- TARGET ---
    target_status = "CANDIDATE" if account_unknown else "KNOWN"
    target = _mix_state(
        status=target_status,
        btc=(target_spot or policy["btc_default_band"])["btc"] if target_spot else None,
        eth=(target_spot or policy["btc_default_band"])["eth"] if target_spot else None,
        usdt=(target_spot or policy["btc_default_band"])["usdt"] if target_spot else None,
        btc_overlay=target_btc_o,
        eth_overlay=target_eth_o,
        event_increment=target_event_inc,
    )

    # --- DELTA ---
    if current_status != "KNOWN" or account_unknown:
        delta = _mix_state(status="UNAVAILABLE", btc=None, eth=None, usdt=None,
                           btc_overlay=None, eth_overlay=None, event_increment=None)
        if account_unknown:
            blockers.append("DELTA_REQUIRES_AUTHORITATIVE_CURRENT")
    else:
        delta = _delta_from(current, target)

    # --- RE-ARM ---
    evidence_epoch = int(rearm.get("evidence_epoch") or 0)
    last_disarm = int(rearm.get("last_disarm_epoch") or 0)
    disarmed = bool(rearm.get("disarmed"))
    if disarmed and evidence_epoch <= last_disarm:
        rearm_state = "DISARMED"
        blockers.append("REARM: same evidence epoch — no reentry")
        open_new_risk = False
    elif disarmed and evidence_epoch > last_disarm:
        rearm_state = "RE_ARM"
        reasons.append("REARM: fresh evidence epoch")
    else:
        rearm_state = "ARMED" if open_new_risk else "DISARMED"

    # --- DECISION KEY / IDEMPOTENCY ---
    pol_hash = policy_hash(policy)
    decision_key = build_brain_decision_key(
        trend_epoch=str(trend_btc.get("epoch") or inp.get("trend_epoch") or "0"),
        value_epoch=str(value_in.get("state_transition_key") or inp.get("value_epoch") or "0"),
        event_id=event_in.get("primary_event_id"),
        event_version=event_in.get("event_version"),
        account_version=inp.get("account_version"),
        position_version=inp.get("position_version"),
        policy_hash=pol_hash,
        strategy_hash=inp.get("strategy_hash") or STRATEGY_HASH_DEFAULT,
    )

    prev = inp.get("previous_decision") or {}
    idempotent = (
        prev.get("decision_key") == decision_key
        and prev.get("based_on_account_version") == inp.get("account_version")
        and decision_key is not None
    )
    if idempotent:
        blockers.append("IDEMPOTENT_DECISION_KEY")
        if delta.get("status") == "AVAILABLE":
            delta = _mix_state(status="IDEMPOTENT", btc=0.0, eth=0.0, usdt=0.0,
                               btc_overlay=0.0, eth_overlay=0.0, event_increment=0.0)

    protection_proposal = None
    prot_in = inp.get("protection") or {}
    if prot_in.get("proposed_stop") and not prot_in.get("confirmed_active_stop"):
        protection_proposal = {
            "protection_change_proposal": prot_in.get("proposed_stop"),
            "state": "PROPOSED",
            "is_active_stop": False,
        }

    btc_or, eth_or, cluster_total = _cluster_overlay_risk(
        trend_btc.get("trend_level", "L0/5"),
        trend_eth.get("trend_level", "L0/5"),
        policy,
    )

    out: Dict[str, Any] = {
        "runtime_kind": RUNTIME_KIND,
        "as_of": as_of,
        "case_id": inp.get("case_id"),
        "decision_key": decision_key,
        "policy_hash": pol_hash,
        "strategy_hash": inp.get("strategy_hash") or STRATEGY_HASH_DEFAULT,
        "based_on_account_version": inp.get("account_version"),
        "based_on_position_version": inp.get("position_version"),
        "input_versions": {
            "trend": trend_btc.get("schema_version") or CONTRACT_HASH_A,
            "value": value_in.get("schema_version") or CONTRACT_HASH_B,
            "event": event_in.get("schema_version") or CONTRACT_HASH_C,
            "account": inp.get("account_version") or "unknown",
            "position": inp.get("position_version") or "unknown",
            "protection": account_truth.get("protection") or "unknown",
        },
        "current_state": current,
        "target_state": target,
        "delta_proposal": delta,
        "spot_action": spot_action,
        "btc_overlay_action": btc_overlay_action,
        "eth_overlay_action": eth_overlay_action,
        "event_action": event_action,
        "crypto_beta_cluster": {
            "btc_request": btc_or,
            "eth_request": eth_or,
            "total_request": cluster_total,
            "cluster_cap": policy["crypto_beta_cluster_cap"]["total"],
            "parameter_status": "PROVISIONAL_E3_PARAM",
        },
        "event_increment_request": event_increment_request,
        "blockers": blockers,
        "reasons": reasons,
        "rearm_state": rearm_state,
        "open_new_risk": open_new_risk and not bool(cross),
        "close_allowed": True,
        "reduce_allowed": True,
        "submit_allowed": False,
        "plan_only": True,
        "idempotent": idempotent,
        "protection_change_proposal": protection_proposal,
        "risk_context_consumed": bool(risk_ctx),
    }
    _assert_runtime_output(out)
    return out


def build_normalized_decision_input(
    *,
    trend_btc: Dict[str, Any],
    trend_eth: Dict[str, Any],
    value_input: Dict[str, Any],
    event_input: Dict[str, Any],
    account_truth: Optional[Dict[str, Any]] = None,
    current_state: Optional[Dict[str, Any]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """Assemble NormalizedDecisionInput — belongs at gate layer, exposed for tests."""
    return {
        "trend_btc": trend_btc,
        "trend_eth": trend_eth,
        "value_input": value_input,
        "event_input": event_input,
        "account_truth": account_truth or {
            "account": "KNOWN", "position": "KNOWN", "protection": "KNOWN",
        },
        "current_state": current_state,
        **extra,
    }


def _assert_runtime_output(out: Dict[str, Any]) -> None:
    if out.get("submit_allowed"):
        raise ValueError("P3 runtime: submit_allowed must be False")
    for key in FORBIDDEN_OUTPUT_EXTENDED:
        if key in out:
            raise ValueError(f"P3 runtime forbids output key: {key}")
