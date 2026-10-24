"""P3-G0 Entry Gate Audit — contract registry + read-only portfolio decision bridge.

NOT P3 production runtime. NOT execution. NOT RiskGate. NOT portfolio_brain_v2.

Proves three P2 inputs can merge under frozen V1.1 semantics without
destroying UNKNOWN / STALE / NOT_CONNECTED discipline.

FROZEN:
  T1–T10 fixtures = ACCEPTANCE AUTHORITY (hash pinned)
  Three engines ≠ voting system
  P0–P5 priority order
  submit_allowed = False
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
from copy import deepcopy
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from aurora.decision_brain_harness import (
    FORBIDDEN_OUTPUT_KEYS,
    HARNESS_KIND,
    evaluate_contract,
    evaluate_pre_submit_revalidation,
    evaluate_protection_authority,
)

GATE_KIND = "P3_ENTRY_GATE_AUDIT"
POLICY_HASH_DEFAULT = "p3-g0-v1"

# Pinned at G0 seal — changing fixtures requires explicit bump + review
T1_T10_FIXTURE_HASH = "5c46f0e54e37a08f"

P0_P5_PRIORITY = (
    "P0 Account / Position / Protection Truth",
    "P1 Risk constraints",
    "P2 Thesis invalidation / Risk reduction",
    "P3 BTC↔ETH Spot Allocation",
    "P4 Trend Overlay",
    "P5 Event Increment",
)

FORBIDDEN_MODULE_FRAGMENTS = frozenset({
    "binance",
    "trading_cycle",
    "risk_gate",
    "execution",
    "portfolio_brain_v2",
    "armed_runtime",
    "open_position",
    "close_position",
    "submit_order",
})

FORBIDDEN_OUTPUT_EXTENDED: FrozenSet[str] = FORBIDDEN_OUTPUT_KEYS | frozenset({
    "order",
    "execution",
    "exchange_qty",
    "buy",
    "sell",
    "open_short",
})

# --- Input contract schemas (version + hash) ---

P2_A_TREND_SCHEMA: Dict[str, Any] = {
    "schema_version": "p2-a-trend-v1",
    "required_fields": (
        "trend_direction",
        "trend_level",
        "action_eligibility",
        "freshness",
        "blockers",
    ),
    "unknown_semantics": "UNKNOWN ≠ neutral ≠ zero ≠ HOLD",
}

P2_B_VALUE_SCHEMA: Dict[str, Any] = {
    "schema_version": "p2-b-value-v1",
    "required_fields": (
        "value_zone",
        "allocation_signal",
        "allocation_state",
        "blockers",
    ),
    "unknown_semantics": "VALUE_TRUTH_UNKNOWN blocks new reallocation",
}

P2_C_EVENT_SCHEMA: Dict[str, Any] = {
    "schema_version": "p2-c-event-v1",
    "required_fields": (
        "observation_state",
        "official_source_ingestion",
        "event_state",
        "primary_event_id",
        "source_health_summary",
    ),
    "unknown_semantics": "NOT_CONNECTED ≠ NO_EVENT_OBSERVED",
}


def _schema_hash(schema: Dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(schema, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]


CONTRACT_HASH_A = _schema_hash(P2_A_TREND_SCHEMA)
CONTRACT_HASH_B = _schema_hash(P2_B_VALUE_SCHEMA)
CONTRACT_HASH_C = _schema_hash(P2_C_EVENT_SCHEMA)


def get_input_contract_registry() -> Dict[str, Any]:
    return {
        "P2-A": {**P2_A_TREND_SCHEMA, "contract_hash": CONTRACT_HASH_A},
        "P2-B": {**P2_B_VALUE_SCHEMA, "contract_hash": CONTRACT_HASH_B},
        "P2-C": {**P2_C_EVENT_SCHEMA, "contract_hash": CONTRACT_HASH_C},
        "T1-T10_fixture_hash": T1_T10_FIXTURE_HASH,
        "policy_hash": POLICY_HASH_DEFAULT,
    }


def verify_t1_t10_fixture_integrity(fixture_path: str) -> Tuple[bool, str]:
    with open(fixture_path, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()[:16]
    return digest == T1_T10_FIXTURE_HASH, digest


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
    return [module for frag in FORBIDDEN_MODULE_FRAGMENTS if frag in mod]


def normalize_trend_decision_input(
    trend_quant: Dict[str, Any],
    *,
    asset: str = "btc",
) -> Dict[str, Any]:
    snap = trend_quant.get(asset) or {}
    return {
        "schema_version": P2_A_TREND_SCHEMA["schema_version"],
        "contract_hash": CONTRACT_HASH_A,
        "asset": asset.upper(),
        "trend_direction": snap.get("trend_direction") or snap.get("dir") or "UNKNOWN",
        "trend_level": snap.get("trend_level") or snap.get("level") or "L0/5",
        "action_eligibility": snap.get("action_eligibility") or "BLOCK_NEW_RISK",
        "freshness": snap.get("freshness") or "unknown",
        "blockers": list(snap.get("blockers") or []),
        "funding_state": snap.get("funding_state") or "UNKNOWN",
        "epoch": snap.get("epoch") or trend_quant.get("epoch"),
    }


def normalize_value_decision_input(eth_btc_bundle: Dict[str, Any]) -> Dict[str, Any]:
    alloc = eth_btc_bundle.get("allocation") or {}
    zone = eth_btc_bundle.get("value_zone") or "UNKNOWN"
    return {
        "schema_version": P2_B_VALUE_SCHEMA["schema_version"],
        "contract_hash": CONTRACT_HASH_B,
        "value_zone": zone,
        "allocation_signal": alloc.get("allocation_signal") or eth_btc_bundle.get("signal") or "NO_REALLOCATION",
        "allocation_state": alloc.get("state") or eth_btc_bundle.get("allocation_state") or "BTC_DEFAULT",
        "blockers": list(eth_btc_bundle.get("blockers") or []) + list(alloc.get("blockers") or []),
        "freshness": eth_btc_bundle.get("freshness") or "unknown",
        "state_transition_key": alloc.get("state_transition_key"),
    }


def normalize_event_decision_input(event_bundle: Dict[str, Any]) -> Dict[str, Any]:
    primary = None
    if event_bundle.get("items"):
        pid = event_bundle.get("primary_event_id")
        for it in event_bundle["items"]:
            if it.get("event_id") == pid or it.get("event_key") == pid:
                primary = it
                break
        if primary is None:
            primary = event_bundle["items"][0]
    elig = (primary or {}).get("eligibility") or {}
    impact = (primary or {}).get("impact") or {}
    return {
        "schema_version": P2_C_EVENT_SCHEMA["schema_version"],
        "contract_hash": CONTRACT_HASH_C,
        "observation_state": event_bundle.get("observation_state") or "UNKNOWN",
        "official_source_ingestion": event_bundle.get("official_source_ingestion") or "NOT_CONNECTED",
        "event_state": event_bundle.get("event_state") or "UNKNOWN",
        "source_health_summary": event_bundle.get("source_health_summary") or "UNKNOWN",
        "primary_event_id": event_bundle.get("primary_event_id"),
        "event_version": (primary or {}).get("event_version"),
        "evidence_grade": impact.get("evidence_grade") or "E0",
        "boost_eligibility": elig.get("boost_eligibility") or "NO_BOOST",
        "action_state": elig.get("action_state") or "NONE",
        "retracted": bool((primary or {}).get("left", {}).get("retracted")),
    }


def build_brain_decision_key(
    *,
    trend_epoch: Optional[str] = None,
    value_epoch: Optional[str] = None,
    event_id: Optional[str] = None,
    event_version: Optional[int] = None,
    account_version: Optional[str] = None,
    position_version: Optional[str] = None,
    policy_hash: str = POLICY_HASH_DEFAULT,
    strategy_hash: str = "strategy-v1",
) -> str:
    payload = {
        "trend_epoch": trend_epoch or "0",
        "value_epoch": value_epoch or "0",
        "event_id": event_id or "none",
        "event_version": event_version or 0,
        "account_version": account_version or "0",
        "position_version": position_version or "0",
        "policy_hash": policy_hash,
        "strategy_hash": strategy_hash,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode()
    ).hexdigest()[:16]


def _zone_to_harness(zone: str) -> str:
    z = (zone or "").upper().replace("_", " ")
    if "DEEP" in z and "CHEAP" in z:
        return "DEEP CHEAP"
    if "CHEAP" in z:
        return "CHEAP"
    if "EXPENSIVE" in z:
        return "EXPENSIVE"
    return "FAIR"


def _signal_to_harness(signal: str) -> str:
    m = {
        "INCREASE_ETH_ELIGIBLE": "INCREASE_ETH",
        "WATCH_ETH": "WATCH_ETH",
        "HOLD_BTC": "HOLD_BTC",
        "NO_REALLOCATION": "HOLD_BTC",
    }
    return m.get(signal, signal)


def compose_harness_input(
    *,
    trend_btc: Dict[str, Any],
    trend_eth: Dict[str, Any],
    value_input: Dict[str, Any],
    event_input: Dict[str, Any],
    current_state: Optional[Dict[str, Any]] = None,
    account_truth: Optional[Dict[str, Any]] = None,
    risk: Optional[Dict[str, Any]] = None,
    rearm: Optional[Dict[str, Any]] = None,
    close_condition: bool = False,
    case_id: str = "COMPOSED",
) -> Dict[str, Any]:
    """Map frozen P2 decision inputs → V1.1 harness dict (not voting)."""
    ev_grade = event_input.get("evidence_grade") or "E0"
    ev_action = "NONE"
    ev_status = "NONE"

    if event_input.get("retracted"):
        ev_status = "RETRACTED"
    elif event_input.get("observation_state") == "SOURCE_NOT_CONNECTED":
        ev_grade = "E0"
        ev_action = "NONE"
        ev_status = "NOT_CONNECTED"
    elif event_input.get("boost_eligibility") == "EVENT_BOOST_ELIGIBLE":
        ev_action = "ELIGIBLE"
        ev_status = "CONFIRMED"
    elif event_input.get("boost_eligibility") == "RISK_OFF_ELIGIBLE":
        ev_action = "RISK_OFF"
        ev_status = "CONFIRMED"
    elif event_input.get("action_state") in ("CONFIRMED", "WATCH"):
        ev_status = event_input.get("action_state")

    return {
        "case_id": case_id,
        "current_state": deepcopy(current_state or {
            "spot": {"btc": 80.0, "eth": 10.0, "usdt": 10.0},
            "overlay": {"btc": 10.0, "eth": 0.0},
            "event_increment_risk": 0.0,
        }),
        "account_truth": dict(account_truth or {
            "account": "KNOWN",
            "position": "KNOWN",
            "protection": "KNOWN",
        }),
        "trend": {
            "btc": {
                "level": trend_btc.get("trend_level", "L0/5"),
                "direction": trend_btc.get("trend_direction", "UNKNOWN"),
            },
            "eth": {
                "level": trend_eth.get("trend_level", "L0/5"),
                "direction": trend_eth.get("trend_direction", "UNKNOWN"),
            },
        },
        "eth_btc_value": {
            "zone": _zone_to_harness(value_input.get("value_zone", "FAIR")),
            "signal": _signal_to_harness(value_input.get("allocation_signal", "HOLD_BTC")),
        },
        "event": {
            "evidence_grade": ev_grade,
            "action_eligibility": ev_action,
            "status": ev_status,
        },
        "risk": dict(risk or {
            "per_trade_loss_budget": 0.0075,
            "cluster_loss_budget": 0.0100,
            "event_increment_budget": 0.0030,
        }),
        "rearm": dict(rearm or {"disarmed": False, "evidence_epoch": 1, "last_disarm_epoch": 0}),
        "close_condition": close_condition,
    }


def evaluate_portfolio_decision_candidate(inp: Dict[str, Any]) -> Dict[str, Any]:
    """Read-only P3 candidate — CURRENT / TARGET / DELTA, never ORDER."""
    harness_in = inp.get("harness_input")
    if harness_in is None:
        harness_in = compose_harness_input(
            trend_btc=inp["trend_btc"],
            trend_eth=inp["trend_eth"],
            value_input=inp["value_input"],
            event_input=inp["event_input"],
            current_state=inp.get("current_state"),
            account_truth=inp.get("account_truth"),
            risk=inp.get("risk"),
            rearm=inp.get("rearm"),
            close_condition=bool(inp.get("close_condition")),
            case_id=inp.get("case_id", "P3-CANDIDATE"),
        )

    prior_key = (inp.get("previous_decision") or {}).get("brain_decision_key")
    decision_key = inp.get("brain_decision_key") or build_brain_decision_key(
        trend_epoch=str(inp.get("trend_epoch") or "0"),
        value_epoch=str(inp.get("value_epoch") or "0"),
        event_id=inp.get("event_input", {}).get("primary_event_id"),
        event_version=inp.get("event_input", {}).get("event_version"),
        account_version=inp.get("account_version"),
        position_version=inp.get("position_version"),
        policy_hash=inp.get("policy_hash") or POLICY_HASH_DEFAULT,
        strategy_hash=inp.get("strategy_hash") or "strategy-v1",
    )

    core = evaluate_contract(harness_in)
    account_unknown = (harness_in.get("account_truth") or {}).get("account") == "UNKNOWN"
    position_unknown = (harness_in.get("account_truth") or {}).get("position") == "UNKNOWN"

    delta_status = "AVAILABLE"
    blockers = list(core.get("blockers") or [])
    if account_unknown:
        delta_status = "UNAVAILABLE"
        if "ACCOUNT_TRUTH_UNKNOWN" not in blockers:
            blockers.append("ACCOUNT_TRUTH_UNKNOWN")
    if position_unknown:
        blockers.append("POSITION_TRUTH_UNKNOWN")
        if core.get("open_iff_pass"):
            delta_status = "UNAVAILABLE"

    trend_btc_in = inp.get("trend_btc") or {}
    cross_violations = audit_unknown_cross_engine(
        trend_btc_in,
        inp.get("value_input") or {},
        inp.get("event_input") or {},
    )
    blockers.extend(cross_violations)

    idempotent = prior_key == decision_key and prior_key is not None
    if idempotent:
        blockers.append("IDEMPOTENT_DECISION_KEY")

    block_new_risk = bool(core.get("block_new_risk")) or bool(cross_violations) or position_unknown

    out = {
        "gate_kind": GATE_KIND,
        "harness_kind": HARNESS_KIND,
        "case_id": core.get("case_id"),
        "brain_decision_key": decision_key,
        "current_state": harness_in.get("current_state"),
        "target_state": core.get("target_state"),
        "delta_proposal": core.get("delta_proposal"),
        "delta_status": delta_status,
        "blockers": blockers,
        "reasons": core.get("reasons"),
        "allocation_signal": core.get("allocation_signal"),
        "spot_action": core.get("spot_action"),
        "overlay_action": core.get("overlay_action"),
        "event_increment_budget": core.get("event_increment_budget"),
        "cluster_overlay_risk": core.get("cluster_overlay_risk"),
        "crypto_beta_cluster": core.get("cluster_overlay_risk"),
        "open_iff_pass": core.get("open_iff_pass") and not cross_violations,
        "block_new_risk": block_new_risk,
        "close_allowed": core.get("close_allowed"),
        "reduce_allowed": core.get("reduce_allowed"),
        "rearm_state": core.get("rearm_state"),
        "submit_allowed": False,
        "plan_only": True,
        "idempotent": idempotent,
        "p0_p5_priority": list(P0_P5_PRIORITY),
        "input_contracts": {
            "P2-A": CONTRACT_HASH_A,
            "P2-B": CONTRACT_HASH_B,
            "P2-C": CONTRACT_HASH_C,
        },
    }
    _assert_gate_output(out)
    return out


def audit_unknown_cross_engine(
    trend_btc: Dict[str, Any],
    value_input: Dict[str, Any],
    event_input: Dict[str, Any],
) -> List[str]:
    """G3 — UNKNOWN must not be out-voted by other engines."""
    violations: List[str] = []
    trend_unknown = (
        trend_btc.get("trend_direction") == "UNKNOWN"
        or trend_btc.get("trend_level", "L0/5") == "L0/5"
        or "UNKNOWN" in (trend_btc.get("blockers") or [])
    )
    value_push = value_input.get("allocation_signal") in ("INCREASE_ETH_ELIGIBLE", "ALLOCATE_ETH")
    event_push = event_input.get("boost_eligibility") == "EVENT_BOOST_ELIGIBLE"
    if trend_unknown and (value_push or event_push):
        violations.append("TREND_TRUTH_UNKNOWN cannot be overridden by Value/Event vote")
    if event_input.get("observation_state") == "SOURCE_NOT_CONNECTED":
        if event_input.get("boost_eligibility") == "EVENT_BOOST_ELIGIBLE":
            violations.append("NOT_CONNECTED cannot yield EVENT_BOOST_ELIGIBLE")
    return violations


def run_entry_gate_audit() -> Dict[str, Any]:
    """Run full G0 registry snapshot for documentation."""
    fixture_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "tests", "fixtures", "decision_brain_v1_1_cases.py",
    )
    ok, digest = verify_t1_t10_fixture_integrity(fixture_path)
    gate_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "decision_brain_entry_gate.py",
    )
    imports_clean = not scan_forbidden_imports(gate_path)
    return {
        "gate_kind": GATE_KIND,
        "status": "PASS" if ok and imports_clean else "FAIL",
        "t1_t10_fixture_hash_ok": ok,
        "t1_t10_fixture_digest": digest,
        "input_contracts": get_input_contract_registry(),
        "forbidden_imports_clean": imports_clean,
        "submit_allowed": False,
        "p3_runtime": "GO_READ_ONLY_ONLY" if ok and imports_clean else "HOLD",
    }


def _assert_gate_output(out: Dict[str, Any]) -> None:
    if out.get("submit_allowed"):
        raise ValueError("P3 gate: submit_allowed must remain False")
    for key in FORBIDDEN_OUTPUT_EXTENDED:
        if key in out:
            raise ValueError(f"P3 gate forbids output key: {key}")
