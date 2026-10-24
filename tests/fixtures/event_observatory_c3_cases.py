"""P2-C.3 Event Observatory mirror — CONTRACT FIXTURES."""
from __future__ import annotations

from typing import Any, Dict, List

T0 = 1_725_900_000_000
T1 = T0 + 60_000

CPI_KEY = "US_CPI_2026_08"


def _cpi_obs(**kw: Any) -> Dict[str, Any]:
    base = {
        "event_key": CPI_KEY,
        "source_id": "BLS",
        "event_class": "CPI_RELEASE",
        "title": "US CPI RELEASE",
        "factual_claim": "Headline CPI YoY",
        "event_time": "2026-08-01T00:00:00Z",
        "actual_value": 2.8,
        "previous_value": 3.2,
        "payload": {"actual_yoy": 2.8},
    }
    base.update(kw)
    return base


def _market_partial() -> Dict[str, Any]:
    return {
        "btc_pre_price": 100.0,
        "btc_post_price": 101.0,
        "eth_pre_price": 50.0,
        "eth_post_price": 50.5,
        "btc_atr": 1.0,
        "eth_atr": 1.0,
        "freshness": "ok",
        "assessment_time_ms": T1,
    }


def _market_unknown() -> Dict[str, Any]:
    return {"freshness": "ok", "assessment_time_ms": T1}


def _market_most() -> Dict[str, Any]:
    m = _market_partial()
    m["btc_post_price"] = 103.0
    return m


def _btc_l4() -> Dict[str, Any]:
    return {"trend_direction": "BULL", "trend_level": "L4/5", "level": "L4/5"}


def _btc_l1() -> Dict[str, Any]:
    return {"trend_direction": "BULL", "trend_level": "L1/5", "level": "L1/5"}


def _btc_l5() -> Dict[str, Any]:
    return {"trend_direction": "BULL", "trend_level": "L5/5", "level": "L5/5"}


# Scenario A — E2-ish confirmed, priced_in UNKNOWN, NO BOOST
SCENARIO_A = {
    "case_id": "C3-A",
    "official_sources_connected": True,
    "fixture_pipeline": [{
        "observation": _cpi_obs(actual_value=2.9, previous_value=3.0),
        "observed_at_ms": T1,
        "market_context": _market_unknown(),
    }],
    "btc_trend": _btc_l4(),
    "as_of_ms": T1 + 30_000,
}

# Scenario B — EVENT_BOOST_ELIGIBLE
SCENARIO_B = {
    "case_id": "C3-B",
    "official_sources_connected": True,
    "fixture_pipeline": [{
        "observation": _cpi_obs(),
        "observed_at_ms": T1,
        "market_context": _market_partial(),
    }],
    "btc_trend": _btc_l4(),
    "as_of_ms": T1 + 30_000,
}

# Scenario C — RISK_OFF systemic + L5
SCENARIO_C = {
    "case_id": "C3-C",
    "official_sources_connected": True,
    "fixture_pipeline": [{
        "observation": {
            "event_key": "EXCHANGE_FAIL_2026",
            "source_id": "SEC",
            "event_class": "MAJOR_EXCHANGE_FAILURE",
            "title": "EXCHANGE SYSTEMIC FAILURE",
            "factual_claim": "Major exchange insolvency confirmed",
            "event_time": "2026-09-10T10:00:00Z",
            "payload": {"formal_document": True},
        },
        "observed_at_ms": T1,
        "market_context": _market_most(),
    }],
    "btc_trend": _btc_l5(),
    "as_of_ms": T1 + 30_000,
}

RETRACTION_SCENARIO = {
    "case_id": "C3-RETRACTED",
    "official_sources_connected": True,
    "fixture_pipeline": [
        {"observation": _cpi_obs(), "observed_at_ms": T1, "market_context": _market_partial()},
        {"retraction": True, "event_key": CPI_KEY, "observation": {"source_id": "BLS"}, "observed_at_ms": T1 + 60_000},
    ],
    "btc_trend": _btc_l4(),
    "as_of_ms": T1 + 120_000,
}

ALL_C3_CASES = [SCENARIO_A, SCENARIO_B, SCENARIO_C, RETRACTION_SCENARIO]
