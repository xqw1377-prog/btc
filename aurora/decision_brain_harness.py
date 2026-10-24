"""Decision Brain V1.1 CONTRACT HARNESS — offline reference evaluator only.

NOT P3 production implementation.
NOT execution authorization.
NOT connected to exchange, WebSocket, or writable clients.

Produces: TargetState, DeltaProposal, Blockers, Reasons, RearmState.
Must NOT produce: order_id, client_order_id, exchange_qty, submit(), execute().
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple

HARNESS_KIND = "CONTRACT_HARNESS_ONLY"
FORBIDDEN_OUTPUT_KEYS = frozenset({
    "order_id",
    "client_order_id",
    "exchange_qty",
    "submit",
    "execute",
})

# PROVISIONAL_E3_PARAM — used only inside harness for T2/T3 arithmetic
_DEFAULT_PER_TRADE = 0.0075
_DEFAULT_CLUSTER = 0.0100
_DEFAULT_EVENT_INCREMENT = 0.0030


def _level_num(level: str) -> int:
    if not level:
        return 0
    for ch in level:
        if ch.isdigit():
            return int(ch)
    return 0


def _spot(state: Dict[str, Any]) -> Dict[str, float]:
    return dict(state.get("spot") or {"btc": 0, "eth": 0, "usdt": 0})


def _overlay(state: Dict[str, Any]) -> Dict[str, float]:
    return dict(state.get("overlay") or {"btc": 0, "eth": 0})


def _clone_state(state: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "spot": _spot(state),
        "overlay": _overlay(state),
        "event_increment_risk": float(state.get("event_increment_risk") or 0),
    }


def _delta(current: Dict[str, Any], target: Dict[str, Any]) -> Dict[str, Any]:
    cs, ts = _spot(current), _spot(target)
    co, to = _overlay(current), _overlay(target)
    return {
        "spot_btc": round(ts.get("btc", 0) - cs.get("btc", 0), 4),
        "spot_eth": round(ts.get("eth", 0) - cs.get("eth", 0), 4),
        "spot_usdt": round(ts.get("usdt", 0) - cs.get("usdt", 0), 4),
        "overlay_btc": round(to.get("btc", 0) - co.get("btc", 0), 4),
        "overlay_eth": round(to.get("eth", 0) - co.get("eth", 0), 4),
        "event_increment_risk": round(
            float(target.get("event_increment_risk") or 0)
            - float(current.get("event_increment_risk") or 0),
            6,
        ),
    }


def _p0_unknown(inp: Dict[str, Any]) -> List[str]:
    blockers: List[str] = []
    acct = inp.get("account_truth") or {}
    for key in ("account", "position", "protection"):
        if (acct.get(key) or "UNKNOWN") == "UNKNOWN":
            blockers.append(f"P0:{key}_UNKNOWN")
    return blockers


def _cluster_overlay_risk(
    btc_level: str,
    eth_level: str,
    *,
    per_trade: float,
    cluster_budget: float,
) -> Tuple[float, float, float]:
    """T2: CRYPTO_BETA_CLUSTER — split cluster; neither gets full per_trade if both L3+."""
    bn = _level_num(btc_level)
    en = _level_num(eth_level)
    if bn < 3 and en < 3:
        return 0.0, 0.0, 0.0
    if bn >= 3 and en >= 3:
        btc_share = 0.7
        eth_share = 0.3
        btc_r = min(per_trade, cluster_budget * btc_share)
        eth_r = min(per_trade, cluster_budget * eth_share)
        return btc_r, eth_r, btc_r + eth_r
    if bn >= 3:
        return min(per_trade, cluster_budget), 0.0, min(per_trade, cluster_budget)
    return 0.0, min(per_trade, cluster_budget), min(per_trade, cluster_budget)


def evaluate_contract(inp: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate V1.1 Decision Brain contract from pure dict inputs."""
    case_id = inp.get("case_id", "UNKNOWN")
    current = _clone_state(inp.get("current_state") or {})
    target = _clone_state(current)
    reasons: List[str] = []
    blockers: List[str] = list(inp.get("blockers") or [])

    trend = inp.get("trend") or {}
    eth_btc = inp.get("eth_btc_value") or {}
    event = inp.get("event") or {}
    risk = inp.get("risk") or {}
    rearm_in = inp.get("rearm") or {}

    per_trade = float(risk.get("per_trade_loss_budget") or _DEFAULT_PER_TRADE)
    cluster_budget = float(risk.get("cluster_loss_budget") or _DEFAULT_CLUSTER)
    event_inc_cap = float(risk.get("event_increment_budget") or _DEFAULT_EVENT_INCREMENT)

    btc_level = (trend.get("btc") or {}).get("level", "L0/5")
    eth_level = (trend.get("eth") or {}).get("level", "L0/5")

    allocation_signal = "HOLD_BTC"
    spot_action = "NO_CHANGE"
    overlay_action = "HOLD"
    event_increment = 0.0
    open_new_risk = True
    close_allowed = True
    reduce_allowed = True

    p0 = _p0_unknown(inp)
    if p0:
        blockers.extend(p0)
        open_new_risk = False
        reasons.append("P0 truth incomplete — BLOCK NEW RISK")

    # P2 — thesis invalidation / close (T6)
    close_condition = bool(inp.get("close_condition"))
    if close_condition:
        reasons.append("P2: close/reduce condition active")
        overlay_action = "CLOSE_OVERLAY"
        target["overlay"] = {"btc": 0, "eth": 0}
        # CLOSE never blocked by open gate

    # P3 — ETH/BTC spot (T1)
    zone = eth_btc.get("zone", "FAIR")
    eth_btc_signal = eth_btc.get("signal", "HOLD_BTC")
    if zone in ("CHEAP", "DEEP CHEAP") and eth_btc_signal in ("ALLOCATE_ETH", "INCREASE_ETH"):
        if _level_num(eth_level) >= 3:
            allocation_signal = "ETH_CONFIRMED"
            spot_action = "REALLOCATE"
            target["spot"] = {
                "btc": max(_spot(current)["btc"] - 10, 0),
                "eth": min(_spot(current)["eth"] + 10, 100),
                "usdt": _spot(current)["usdt"],
            }
            reasons.append("P3: cheap ETH + trend confirmed — ladder realloc")
        else:
            allocation_signal = "WATCH_ETH"
            spot_action = "NO_REALLOCATION"
            reasons.append("P3: cheap ETH but ETH trend L1 — WATCH only (T1)")
    elif eth_btc_signal == "WATCH_ETH":
        allocation_signal = "WATCH_ETH"
        spot_action = "NO_REALLOCATION"

    # P4 — Trend overlay (T2)
    btc_or, eth_or, cluster_used = _cluster_overlay_risk(
        btc_level, eth_level, per_trade=per_trade, cluster_budget=cluster_budget,
    )
    if not close_condition and open_new_risk:
        if btc_or > 0 or eth_or > 0:
            overlay_action = "INCREASE_OVERLAY"
            target["overlay"] = {
                "btc": btc_or * 100,  # harness: risk pct → display overlay weight
                "eth": eth_or * 100,
            }
            reasons.append(
                f"P4: cluster overlay btc={btc_or:.4f} eth={eth_or:.4f} "
                f"sum={cluster_used:.4f} <= {cluster_budget:.4f}"
            )

    # P5 — Event boost (T3, T4, T7)
    ev_grade = event.get("evidence_grade", "E0")
    ev_action = event.get("action_eligibility", "NONE")
    ev_status = event.get("status", "NONE")

    if ev_status == "RETRACTED":
        target["event_increment_risk"] = 0.0
        event_increment = 0.0
        reasons.append("P7: event RETRACTED — increment removed, no auto reverse")
    elif ev_grade in ("A", "A+") or ev_grade == "E3":
        if _level_num(btc_level) < 3 and _level_num(eth_level) < 3:
            reasons.append("P5: high event evidence but trend L1 — NO BOOST (T4)")
            target["event_increment_risk"] = 0.0
        elif ev_action in ("ELIGIBLE", "ACTIVE") and open_new_risk and not close_condition:
            base_risk = cluster_used
            event_increment = min(event_inc_cap, cluster_budget - base_risk)
            if event_increment < 0:
                event_increment = 0.0
            target["event_increment_risk"] = event_increment
            reasons.append(
                f"P5: incremental event budget {event_increment:.4f} "
                f"(not double-counted with trend base {base_risk:.4f})"
            )
        else:
            target["event_increment_risk"] = 0.0
    else:
        target["event_increment_risk"] = 0.0

    if not open_new_risk and not close_condition:
        overlay_action = "BLOCKED" if overlay_action == "INCREASE_OVERLAY" else overlay_action
        target["overlay"] = _overlay(current)
        target["event_increment_risk"] = float(current.get("event_increment_risk") or 0)
        spot_action = "NO_REALLOCATION" if spot_action == "REALLOCATE" else spot_action
        if allocation_signal.startswith("ETH"):
            allocation_signal = "WATCH_ETH"
    elif not open_new_risk and close_condition:
        overlay_action = "CLOSE_OVERLAY"

    # T8 — RE-ARM
    evidence_epoch = int(rearm_in.get("evidence_epoch") or 0)
    last_disarm = int(rearm_in.get("last_disarm_epoch") or 0)
    disarmed = bool(rearm_in.get("disarmed"))
    if disarmed and evidence_epoch <= last_disarm:
        rearm_state = "DISARMED"
        blockers.append("REARM: same evidence epoch — NO REENTRY (T8)")
        open_new_risk = False
        target["overlay"] = _overlay(current)
    elif disarmed and evidence_epoch > last_disarm:
        rearm_state = "RE_ARM"
        reasons.append("REARM: fresh evidence epoch — re-arm allowed")
    else:
        rearm_state = "ARMED" if open_new_risk else "DISARMED"

    delta = _delta(current, target)
    open_iff_pass = open_new_risk and not blockers and not close_condition

    candidate: Dict[str, Any] = {
        "harness_kind": HARNESS_KIND,
        "case_id": case_id,
        "target_state": target,
        "delta_proposal": delta,
        "blockers": blockers,
        "reasons": reasons,
        "rearm_state": rearm_state,
        "allocation_signal": allocation_signal,
        "spot_action": spot_action,
        "overlay_action": overlay_action,
        "event_increment_budget": event_increment,
        "cluster_overlay_risk": {
            "btc": btc_or,
            "eth": eth_or,
            "total": cluster_used,
            "cluster_cap": cluster_budget,
            "per_trade_cap": per_trade,
        },
        "open_iff_pass": open_iff_pass,
        "block_new_risk": not open_new_risk or bool(blockers),
        "close_allowed": close_allowed,
        "reduce_allowed": reduce_allowed,
        "submit_allowed": False,  # harness never authorizes submit
    }
    _assert_harness_output(candidate)
    return candidate


def evaluate_pre_submit_revalidation(
    plan_snapshot: Dict[str, Any],
    submit_snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    """T9 / A1 — plan PASS ≠ submit PASS if versions drift."""
    changed = []
    for key in (
        "market_snapshot_version",
        "account_snapshot_version",
        "position_version",
        "open_order_version",
        "policy_hash",
        "strategy_hash",
    ):
        if plan_snapshot.get(key) != submit_snapshot.get(key):
            changed.append(key)
    if changed:
        return {
            "harness_kind": HARNESS_KIND,
            "pre_submit_revalidation": "PLAN_EXPIRED",
            "action": "RECOMPUTE",
            "changed_fields": changed,
            "submit_allowed": False,
        }
    return {
        "harness_kind": HARNESS_KIND,
        "pre_submit_revalidation": "PASS",
        "action": "MAY_SUBMIT",
        "changed_fields": [],
        "submit_allowed": True,
    }


def evaluate_protection_authority(
    protection: Dict[str, Any],
) -> Dict[str, Any]:
    """T10 — proposed_stop + ACK only ≠ ACTIVE."""
    proposed = protection.get("proposed_stop")
    ack = protection.get("exchange_ack")
    confirmed = protection.get("confirmed_active_stop")
    if proposed and ack and not confirmed:
        state = "ACK_ONLY"
        is_active = False
    elif confirmed:
        state = "ACTIVE"
        is_active = True
    elif proposed:
        state = "PROPOSED"
        is_active = False
    else:
        state = "NONE"
        is_active = False
    return {
        "harness_kind": HARNESS_KIND,
        "protection_state": state,
        "is_active_stop": is_active,
        "proposed_stop": proposed,
        "approved_stop": protection.get("approved_stop"),
    }


def _assert_harness_output(candidate: Dict[str, Any]) -> None:
    for key in FORBIDDEN_OUTPUT_KEYS:
        if key in candidate:
            raise ValueError(f"harness must not emit forbidden key: {key}")
