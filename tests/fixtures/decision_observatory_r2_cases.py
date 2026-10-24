"""P3-R2 Decision Observatory mirror — CONTRACT FIXTURES."""
from __future__ import annotations

from typing import Any, Dict

from tests.fixtures.event_observatory_c3_cases import SCENARIO_B, SCENARIO_C

TREND_L5_L3: Dict[str, Any] = {
    "btc": {
        "trend_direction": "BULL",
        "trend_level": "L5/5",
        "action_eligibility": "LONG_ELIGIBLE",
        "freshness": "ok",
        "blockers": [],
        "epoch": "t-l5",
    },
    "eth": {
        "trend_direction": "BULL",
        "trend_level": "L3/5",
        "action_eligibility": "LONG_ELIGIBLE",
        "freshness": "ok",
        "blockers": [],
        "epoch": "t-l3",
    },
}

ETH_BTC_CONFIRMED: Dict[str, Any] = {
    "value_zone": "CHEAP",
    "freshness": "ok",
    "blockers": [],
    "allocation": {
        "state": "ETH_CONFIRMED",
        "allocation_signal": "INCREASE_ETH_ELIGIBLE",
        "state_transition_key": "v-confirmed",
        "blockers": [],
    },
}

ETH_BTC_FAIR: Dict[str, Any] = {
    "value_zone": "FAIR",
    "freshness": "ok",
    "blockers": [],
    "allocation": {
        "state": "BTC_DEFAULT",
        "allocation_signal": "NO_REALLOCATION",
        "state_transition_key": "v-fair",
        "blockers": [],
    },
}

EVENT_NOT_CONNECTED: Dict[str, Any] = {
    "capability": "READ-ONLY-SEMANTICS",
    "observation_state": "SOURCE_NOT_CONNECTED",
    "official_source_ingestion": "NOT_CONNECTED",
    "source_health_summary": "SOURCE_NOT_CONNECTED",
    "event_state": "UNKNOWN",
    "items": [],
    "as_of": "2026-09-10T02:00:00Z",
}

EXCHANGE_UNKNOWN: Dict[str, Any] = {
    "status": "unknown",
    "actual_mix": {"percent": None, "values": None},
    "positions": "UNKNOWN",
}

EXCHANGE_OK_NO_MIX: Dict[str, Any] = {
    "status": "ok",
    "actual_mix": {"percent": None, "values": {"btc": "0.1", "eth": "1.0", "usdt": "1000"}},
    "positions": "FLAT",
}

AUTHORITATIVE_CURRENT: Dict[str, Any] = {
    "status": "KNOWN",
    "btc": 80.0,
    "eth": 10.0,
    "usdt": 10.0,
    "btc_overlay": 0.007,
    "eth_overlay": 0.0,
    "event_increment": 0.0,
}

RISK_OFF_SCENARIO = SCENARIO_C
BOOST_SCENARIO = SCENARIO_B
