"""P3-R3.0 Risk Contract Harness — CONTRACT FIXTURES."""
from __future__ import annotations

from typing import Any, Dict

from aurora.decision_brain import build_normalized_decision_input, default_decision_policy, evaluate_decision
from tests.fixtures.decision_brain_r1_cases import (
    CURRENT_80_10,
    KNOWN_ACCOUNT,
    TREND_L4_SCHEMA,
    TREND_ETH_L3,
    TREND_L5,
    VALUE_CONFIRMED_SCHEMA,
    VALUE_FAIR_SCHEMA,
    _base,
)


def _candidate(**kw: Any) -> Dict[str, Any]:
    return evaluate_decision(
        build_normalized_decision_input(**_base(**kw)),
        default_decision_policy(),
    )


def _candidate_manual(**overrides: Any) -> Dict[str, Any]:
    base = _candidate()
    base.update(overrides)
    return base


def truth_complete(**kw: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "as_of": "2026-09-10T03:00:00Z",
        "account_truth": {
            "status": "KNOWN",
            "version": "acc-v1",
            "btc_nav": 1.25,
            "equity": 100000.0,
            "available_margin": 50000.0,
            "margin_usage": 0.2,
        },
        "position_truth": {
            "status": "KNOWN",
            "version": "pos-v1",
            "btc_spot": 80.0,
            "eth_spot": 10.0,
            "btc_overlay": 0.007,
            "eth_overlay": 0.0,
        },
        "protection_truth": {
            "status": "KNOWN",
            "version": "prot-v1",
            "stop_plan_state": "AUTHORITATIVE",
            "active_protection_state": "ACTIVE_CONFIRMED",
        },
        "portfolio_risk_truth": {
            "drawdown": 0.05,
            "realized_loss": 0.01,
            "current_cluster_exposure": 0.007,
            "current_overlay_exposure": 0.007,
        },
        "market_cost_truth": {
            "btc_funding": 0.0001,
            "eth_funding": 0.00008,
            "spread": 0.0002,
            "slippage_estimate": 0.0003,
            "freshness": "ok",
        },
        "pending_truth": {
            "pending_order_state": "NONE",
            "pending_plan_state": "NONE",
        },
        "governance": {
            "kill": "CLEAR",
            "incident": "CLEAR",
            "authorization": "DENIED",
        },
    }
    for key, val in kw.items():
        if isinstance(val, dict) and isinstance(base.get(key), dict):
            base[key] = {**base[key], **val}
        else:
            base[key] = val
    return base


# R3-1 — BTC NAV unknown
R3_1 = {
    "case_id": "R3-1",
    "candidate": _candidate(
        trend_btc=TREND_L5,
        account_truth=KNOWN_ACCOUNT,
        current_state=CURRENT_80_10,
    ),
    "truth": truth_complete(account_truth={"btc_nav": None, "status": "UNKNOWN"}),
}

# R3-2 — drawdown unknown
R3_2 = {
    "case_id": "R3-2",
    "candidate": _candidate(trend_btc=TREND_L5, current_state=CURRENT_80_10),
    "truth": truth_complete(portfolio_risk_truth={"drawdown": None}),
}

# R3-3 — brain requests 0.01 cluster, policy allows 0.006
R3_3 = {
    "case_id": "R3-3",
    "candidate": _candidate(trend_btc=TREND_L5, current_state=CURRENT_80_10),
    "truth": truth_complete(),
    "policy_override": {"cluster_loss_budget": 0.006, "overlay_pool_loss_budget": 0.006},
    "expect_allowed_max": 0.006,
}

# R3-4 — dual overlay cluster
R3_4 = {
    "case_id": "R3-4",
    "candidate": _candidate(
        trend_btc=TREND_L5,
        trend_eth={**TREND_ETH_L3, "trend_level": "L4/5"},
        current_state=CURRENT_80_10,
    ),
    "truth": truth_complete(),
}

# R3-5 — trend + event increment unified budget
R3_5 = {
    "case_id": "R3-5",
    "candidate": _candidate(
        trend_btc=TREND_L5,
        trend_eth={**TREND_ETH_L3, "trend_level": "L4/5"},
        event_input={
            "schema_version": "p2-c-event-v1",
            "observation_state": "EVENT_OBSERVED",
            "boost_eligibility": "EVENT_BOOST_ELIGIBLE",
            "action_state": "INCREMENT",
            "primary_event_id": "EVT-1",
            "event_version": 1,
            "retracted": False,
        },
        current_state=CURRENT_80_10,
    ),
    "truth": truth_complete(),
    "policy_override": {"cluster_loss_budget": 0.010, "event_increment_budget": 0.003},
}

# R3-6 — funding unknown blocks open, not close
R3_6_OPEN = {
    "case_id": "R3-6-open",
    "candidate": _candidate(trend_btc=TREND_L5, current_state=CURRENT_80_10),
    "truth": truth_complete(market_cost_truth={"btc_funding": None, "freshness": "ok"}),
}
R3_6_CLOSE = {
    "case_id": "R3-6-close",
    "candidate": _candidate_manual(
        btc_overlay_action="CLOSE_OVERLAY",
        spot_action="REDUCE_OR_CLOSE",
        thesis_invalidated=True,
        crypto_beta_cluster={"btc_request": 0, "eth_request": 0, "total_request": 0},
    ),
    "truth": truth_complete(market_cost_truth={"btc_funding": None, "freshness": "ok"}),
}

# R3-7 — spread stale
R3_7 = {
    "case_id": "R3-7",
    "candidate": _candidate(trend_btc=TREND_L5, current_state=CURRENT_80_10),
    "truth": truth_complete(market_cost_truth={"freshness": "stale", "spread": None}),
}

# R3-8 — open blocked + thesis invalid defensive survives
R3_8 = {
    "case_id": "R3-8",
    "candidate": _candidate_manual(
        btc_overlay_action="CLOSE_OVERLAY",
        spot_action="REDUCE_OR_CLOSE",
        close_allowed=True,
        reduce_allowed=True,
        crypto_beta_cluster={"btc_request": 0, "eth_request": 0, "total_request": 0},
    ),
    "truth": truth_complete(market_cost_truth={"btc_funding": None}),
}

# R3-9 — position unknown + defensive
R3_9 = {
    "case_id": "R3-9",
    "candidate": _candidate_manual(
        btc_overlay_action="CLOSE_OVERLAY",
        close_allowed=True,
        reduce_allowed=True,
    ),
    "truth": truth_complete(position_truth={"status": "UNKNOWN", "version": None}),
}

# R3-10 — stop plan proposed only
R3_10 = {
    "case_id": "R3-10",
    "candidate": _candidate(trend_btc=TREND_L5, current_state=CURRENT_80_10),
    "truth": truth_complete(protection_truth={"stop_plan_state": "PROPOSED"}),
}

# R3-11 — unit_loss sizing
R3_11 = {
    "case_id": "R3-11",
    "candidate": _candidate(trend_btc=TREND_L5, current_state=CURRENT_80_10),
    "truth": truth_complete(),
    "sizing_low": {
        "entry_estimate": 100000.0,
        "stop_price": 99250.0,
        "adverse_slippage": 50.0,
        "fees": 25.0,
        "stressed_funding": 10.0,
        "q_target": 0.1,
    },
    "sizing_high": {
        "entry_estimate": 100000.0,
        "stop_price": 99250.0,
        "adverse_slippage": 50.0,
        "fees": 25.0,
        "stressed_funding": 500.0,
        "q_target": 0.1,
    },
}

# R3-12 — policy null
R3_12 = {
    "case_id": "R3-12",
    "candidate": _candidate(trend_btc=TREND_L5, current_state=CURRENT_80_10),
    "truth": truth_complete(),
    "policy_override": {"cluster_loss_budget": None},
}

# Kill active
R3_KILL = {
    "case_id": "R3-kill",
    "candidate": _candidate(trend_btc=TREND_L5, current_state=CURRENT_80_10),
    "truth": truth_complete(governance={"kill": "ACTIVE"}),
}

ALL_R3_CASES = [
    R3_1, R3_2, R3_3, R3_4, R3_5, R3_6_OPEN, R3_6_CLOSE, R3_7, R3_8, R3_9,
    R3_10, R3_11, R3_12, R3_KILL,
]
