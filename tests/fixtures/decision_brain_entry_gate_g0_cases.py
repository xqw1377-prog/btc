"""P3-G0 Entry Gate — CONTRACT FIXTURES (not acceptance authority)."""
from __future__ import annotations

from typing import Any, Dict

from aurora.decision_brain_entry_gate import compose_harness_input

NOT_CONNECTED_EVENT = {
    "schema_version": "p2-c-event-v1",
    "observation_state": "SOURCE_NOT_CONNECTED",
    "official_source_ingestion": "NOT_CONNECTED",
    "event_state": "UNKNOWN",
    "source_health_summary": "SOURCE_NOT_CONNECTED",
    "primary_event_id": None,
    "evidence_grade": "E0",
    "boost_eligibility": "NO_BOOST",
    "action_state": "NONE",
    "retracted": False,
}

TREND_L4 = {
    "trend_direction": "BULL",
    "trend_level": "L4/5",
    "action_eligibility": "LONG_ELIGIBLE",
    "freshness": "ok",
    "blockers": [],
}

TREND_UNKNOWN = {
    "trend_direction": "UNKNOWN",
    "trend_level": "L0/5",
    "action_eligibility": "BLOCK_NEW_RISK",
    "freshness": "unknown",
    "blockers": ["HTF_INCOMPLETE"],
}

VALUE_ETH_CONFIRMED = {
    "value_zone": "CHEAP_ETH",
    "allocation_signal": "INCREASE_ETH_ELIGIBLE",
    "allocation_state": "ETH_CONFIRMED",
    "blockers": [],
}

VALUE_FAIR = {
    "value_zone": "FAIR",
    "allocation_signal": "HOLD_BTC",
    "allocation_state": "BTC_DEFAULT",
    "blockers": [],
}

EVENT_ELIGIBLE = {
    "observation_state": "OK",
    "official_source_ingestion": "CONNECTED",
    "event_state": "OK",
    "source_health_summary": "OK",
    "primary_event_id": "US_CPI_2026_08",
    "event_version": 1,
    "evidence_grade": "E3",
    "boost_eligibility": "EVENT_BOOST_ELIGIBLE",
    "action_state": "ELIGIBLE",
    "retracted": False,
}


def g5_not_connected() -> Dict[str, Any]:
    return {
        "case_id": "G5",
        "trend_btc": TREND_L4,
        "trend_eth": TREND_L4,
        "value_input": VALUE_FAIR,
        "event_input": NOT_CONNECTED_EVENT,
    }


def g6_account_unknown() -> Dict[str, Any]:
    return {
        "case_id": "G6",
        "trend_btc": TREND_L4,
        "trend_eth": TREND_L4,
        "value_input": VALUE_ETH_CONFIRMED,
        "event_input": NOT_CONNECTED_EVENT,
        "account_truth": {"account": "UNKNOWN", "position": "KNOWN", "protection": "KNOWN"},
    }


def g7_position_unknown() -> Dict[str, Any]:
    return {
        "case_id": "G7",
        "trend_btc": TREND_L4,
        "trend_eth": TREND_L4,
        "value_input": VALUE_FAIR,
        "event_input": NOT_CONNECTED_EVENT,
        "account_truth": {"account": "KNOWN", "position": "UNKNOWN", "protection": "KNOWN"},
    }


def g8_close_survives() -> Dict[str, Any]:
    return compose_harness_input(
        trend_btc=TREND_L4,
        trend_eth=TREND_L4,
        value_input=VALUE_FAIR,
        event_input=NOT_CONNECTED_EVENT,
        account_truth={"account": "KNOWN", "position": "KNOWN", "protection": "UNKNOWN"},
        close_condition=True,
        case_id="G8",
    )


def g9_cluster() -> Dict[str, Any]:
    return compose_harness_input(
        trend_btc=TREND_L4,
        trend_eth=TREND_L4,
        value_input=VALUE_FAIR,
        event_input=NOT_CONNECTED_EVENT,
        case_id="G9",
    )


def g10_incremental() -> Dict[str, Any]:
    return compose_harness_input(
        trend_btc=TREND_L4,
        trend_eth={"trend_direction": "BULL", "trend_level": "L2/5"},
        value_input=VALUE_FAIR,
        event_input=EVENT_ELIGIBLE,
        case_id="G10",
    )


def g3_vote_violation_inputs() -> Dict[str, Any]:
    return {
        "trend_btc": TREND_UNKNOWN,
        "value_input": VALUE_ETH_CONFIRMED,
        "event_input": EVENT_ELIGIBLE,
    }
