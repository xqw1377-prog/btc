"""P2-C.2 Event Action Eligibility — CONTRACT FIXTURES."""
from __future__ import annotations

from typing import Any, Dict

POLICY = "p2-c2-v1"
T_OBS = "2026-09-10T12:31:00Z"
T_AS_OF_MS = 1_725_900_660_000


def _truth(**kw: Any) -> Dict[str, Any]:
    base = {
        "event_key": "evt-default",
        "event_version": 1,
        "event_class": "CPI_RELEASE",
        "source_id": "BLS",
        "stage": "EVENT_TRUTH",
        "title": "Test event",
        "factual_claim": "—",
        "first_observed_at": T_OBS,
        "last_observed_at": T_OBS,
        "retracted": False,
        "freshness": "ok",
        "payload": {},
    }
    base.update(kw)
    return base


def _market(**kw: Any) -> Dict[str, Any]:
    base = {
        "btc_pre_price": 100.0,
        "btc_post_price": 101.0,
        "eth_pre_price": 50.0,
        "eth_post_price": 50.5,
        "btc_atr": 1.0,
        "eth_atr": 1.0,
        "freshness": "ok",
        "assessment_time_ms": T_AS_OF_MS,
    }
    base.update(kw)
    return base


def _trend_btc(level: str) -> Dict[str, Any]:
    return {"level": level, "epoch": "ep-1"}


def _case(case_id: str, **overrides: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "case_id": case_id,
        "policy_version": POLICY,
        "event_truth": _truth(),
        "market_context": _market(),
        "btc_trend_snapshot": _trend_btc("L4/5"),
        "eth_trend_snapshot": _trend_btc("L3/5"),
        "market_freshness": "ok",
        "previous_event_state": {},
        "as_of": T_OBS,
        "as_of_ms": T_AS_OF_MS,
    }
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            merged = dict(base[k])
            merged.update(v)
            base[k] = merged
        else:
            base[k] = v
    return base


# C2-1 — E0 rumor → WATCH / NO_BOOST
C2_1_E0_RUMOR = _case(
    "C2-1",
    event_truth=_truth(
        event_key="evt-c2-1",
        event_class="MACRO",
        source_quality="UNVERIFIED",
        stage="EXTRACTED_CANDIDATE",
    ),
)

# C2-2 — E1 confirmed, direction UNKNOWN → CONFIRMED / NO_BOOST
C2_2_E1_UNKNOWN_DIR = _case(
    "C2-2",
    event_truth=_truth(
        event_key="evt-c2-2",
        event_class="FED_RATE_DECISION",
        source_id="FED",
        factual_claim="FOMC held rates unchanged",
    ),
    market_context=_market(btc_pre_price=None, btc_post_price=None),
)

# C2-3 — E3 + positive + priced_in MOST → NO_BOOST
C2_3_PRICED_IN_MOST = _case(
    "C2-3",
    event_truth=_truth(
        event_key="evt-c2-3",
        actual_value=2.8,
        previous_value=3.2,
        surprise=-0.2,
    ),
    market_context=_market(btc_post_price=103.0),  # 3 ATR → MOST
)

# C2-4 — E3 + positive + L4 + aligned + PARTIAL → EVENT_BOOST_ELIGIBLE
C2_4_BOOST_ELIGIBLE = _case(
    "C2-4",
    event_truth=_truth(
        event_key="evt-c2-4",
        actual_value=2.8,
        previous_value=3.2,
        surprise=-0.2,
    ),
    market_context=_market(btc_post_price=101.0),  # 1 ATR → PARTIAL
    btc_trend_snapshot=_trend_btc("L4/5"),
)

# C2-5 — E3 positive + BTC L1 → CONFIRMED / NO_BOOST
C2_5_TREND_L1 = _case(
    "C2-5",
    event_truth=_truth(
        event_key="evt-c2-5",
        actual_value=2.8,
        previous_value=3.2,
    ),
    btc_trend_snapshot=_trend_btc("L1/5"),
)

# C2-6 — E3 positive + priced_in UNKNOWN → NO_BOOST
C2_6_PRICED_IN_UNKNOWN = _case(
    "C2-6",
    event_truth=_truth(
        event_key="evt-c2-6",
        actual_value=2.8,
        previous_value=3.2,
    ),
    market_context=_market(
        btc_pre_price=None,
        btc_post_price=None,
        eth_pre_price=None,
        eth_post_price=None,
    ),
)

# C2-7 — E3 negative systemic + BTC L5 bullish → RISK_OFF_ELIGIBLE
C2_7_RISK_OFF_L5 = _case(
    "C2-7",
    event_truth=_truth(
        event_key="evt-c2-7",
        event_class="MAJOR_EXCHANGE_FAILURE",
        source_id="SEC",
        factual_claim="Major exchange insolvency confirmed",
    ),
    btc_trend_snapshot=_trend_btc("L5/5"),
)

# C2-8 — RETRACTED → NONE
C2_8_RETRACTED = _case(
    "C2-8",
    event_truth=_truth(
        event_key="evt-c2-8",
        retracted=True,
        revision_type="RETRACTION",
    ),
)

# C2-9 — stale truth → no new boost
C2_9_STALE = _case(
    "C2-9",
    event_truth=_truth(
        event_key="evt-c2-9",
        actual_value=2.8,
        previous_value=3.2,
        freshness="stale",
    ),
    market_freshness="stale",
)

# C2-10 — idempotent
C2_10_IDEMPOTENT = _case(
    "C2-10",
    event_truth=_truth(
        event_key="evt-c2-10",
        actual_value=2.8,
        previous_value=3.2,
    ),
    previous_event_state={
        "fingerprint": "placeholder",
        "action_state": "CONFIRMED",
        "boost_eligibility": "NO_BOOST",
    },
)

# C2-11 — lookahead
C2_11_LOOKAHEAD = _case(
    "C2-11",
    event_truth=_truth(event_key="evt-c2-11"),
    market_context=_market(future_price_reaction=True),
)

# SEC 2024-01-09 style — social without formal document
SEC_SOCIAL_FAKE_ETF = _case(
    "SEC-SOCIAL-NEG",
    event_truth=_truth(
        event_key="SEC-ETF-SOCIAL-2024",
        event_class="ETF_APPROVAL_REJECTION",
        source_id="SEC",
        source_quality="SOCIAL_ONLY",
        title="Unauthorized SEC social post — ETF approved",
        factual_claim="ETF approved via social account",
        payload={"formal_document": False},
        stage="EXTRACTED_CANDIDATE",
    ),
)

ALL_C2_CASES = [
    C2_1_E0_RUMOR,
    C2_2_E1_UNKNOWN_DIR,
    C2_3_PRICED_IN_MOST,
    C2_4_BOOST_ELIGIBLE,
    C2_5_TREND_L1,
    C2_6_PRICED_IN_UNKNOWN,
    C2_7_RISK_OFF_L5,
    C2_8_RETRACTED,
    C2_9_STALE,
    C2_10_IDEMPOTENT,
    SEC_SOCIAL_FAKE_ETF,
]
