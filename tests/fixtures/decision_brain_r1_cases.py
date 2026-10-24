"""P3-R1 Decision Brain — CONTRACT FIXTURES."""
from __future__ import annotations

from typing import Any, Dict

from tests.fixtures.decision_brain_entry_gate_g0_cases import (
    EVENT_ELIGIBLE,
    NOT_CONNECTED_EVENT,
    TREND_L4,
    VALUE_ETH_CONFIRMED,
    VALUE_FAIR,
)

KNOWN_ACCOUNT = {"account": "KNOWN", "position": "KNOWN", "protection": "KNOWN"}
UNKNOWN_ACCOUNT = {"account": "UNKNOWN", "position": "KNOWN", "protection": "KNOWN"}
PROT_UNKNOWN = {"account": "KNOWN", "position": "KNOWN", "protection": "UNKNOWN"}

CURRENT_80_10 = {
    "status": "KNOWN",
    "btc": 80.0,
    "eth": 10.0,
    "usdt": 10.0,
    "btc_overlay": 0.007,
    "eth_overlay": 0.0,
    "event_increment": 0.0,
}

TREND_L5 = {
    "trend_direction": "BULL",
    "trend_level": "L5/5",
    "action_eligibility": "LONG_ELIGIBLE",
    "freshness": "ok",
    "blockers": [],
    "schema_version": "p2-a-trend-v1",
}

TREND_L4_SCHEMA = {**TREND_L4, "schema_version": "p2-a-trend-v1", "epoch": "t-ep-1"}
TREND_ETH_L3 = {
    "trend_direction": "BULL",
    "trend_level": "L3/5",
    "action_eligibility": "LONG_ELIGIBLE",
    "freshness": "ok",
    "blockers": [],
    "schema_version": "p2-a-trend-v1",
}

VALUE_CONFIRMED_SCHEMA = {**VALUE_ETH_CONFIRMED, "schema_version": "p2-b-value-v1", "state_transition_key": "v-1"}
VALUE_FAIR_SCHEMA = {**VALUE_FAIR, "schema_version": "p2-b-value-v1", "state_transition_key": "v-0"}

EVENT_NC_SCHEMA = {**NOT_CONNECTED_EVENT, "schema_version": "p2-c-event-v1"}
EVENT_ELIG_SCHEMA = {**EVENT_ELIGIBLE, "schema_version": "p2-c-event-v1"}

RISK_OFF_EVENT = {
    **EVENT_ELIGIBLE,
    "schema_version": "p2-c-event-v1",
    "boost_eligibility": "RISK_OFF_ELIGIBLE",
    "action_state": "RISK_OFF",
    "primary_event_id": "EXCHANGE_FAIL",
}


def _base(**kw: Any) -> Dict[str, Any]:
    base = {
        "trend_btc": TREND_L4_SCHEMA,
        "trend_eth": TREND_ETH_L3,
        "value_input": VALUE_FAIR_SCHEMA,
        "event_input": EVENT_NC_SCHEMA,
        "account_truth": KNOWN_ACCOUNT,
        "account_version": "a1",
        "position_version": "p1",
    }
    base.update(kw)
    return base
