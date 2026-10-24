"""Frozen T1–T8 contract case inputs for Decision Brain V1.1 harness.

Pure dict fixtures — no network, no exchange, no mutable account state.
"""
from __future__ import annotations

from typing import Any, Dict

BASE_CURRENT = {
    "spot": {"btc": 80.0, "eth": 10.0, "usdt": 10.0},
    "overlay": {"btc": 10.0, "eth": 0.0},
    "event_increment_risk": 0.0,
}

KNOWN_ACCOUNT = {
    "account": "KNOWN",
    "position": "KNOWN",
    "protection": "KNOWN",
}


def _case(case_id: str, **overrides: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "case_id": case_id,
        "current_state": dict(BASE_CURRENT),
        "account_truth": dict(KNOWN_ACCOUNT),
        "trend": {
            "btc": {"level": "L2/5", "direction": "BULL"},
            "eth": {"level": "L2/5", "direction": "BULL"},
        },
        "eth_btc_value": {"zone": "FAIR", "signal": "HOLD_BTC"},
        "event": {"evidence_grade": "E0", "action_eligibility": "NONE", "status": "NONE"},
        "risk": {
            "per_trade_loss_budget": 0.0075,
            "cluster_loss_budget": 0.0100,
            "event_increment_budget": 0.0030,
        },
        "rearm": {"disarmed": False, "evidence_epoch": 1, "last_disarm_epoch": 0},
        "close_condition": False,
    }
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            merged = dict(base[k])
            merged.update(v)
            base[k] = merged
        else:
            base[k] = v
    return base


T1_ETH_CHEAP_L1 = _case(
    "T1",
    eth_btc_value={"zone": "CHEAP", "signal": "ALLOCATE_ETH"},
    trend={"eth": {"level": "L1/5", "direction": "UNKNOWN"}},
)

T2_BTC_L4_ETH_L4 = _case(
    "T2",
    trend={
        "btc": {"level": "L4/5", "direction": "BULL"},
        "eth": {"level": "L4/5", "direction": "BULL"},
    },
)

T3_TREND_EVENT_SAME_DIR = _case(
    "T3",
    trend={"btc": {"level": "L4/5", "direction": "BULL"}},
    event={
        "evidence_grade": "E3",
        "action_eligibility": "ELIGIBLE",
        "status": "CONFIRMED",
        "direction": "BTC+",
    },
)

T4_APLUS_EVENT_L1 = _case(
    "T4",
    trend={"btc": {"level": "L1/5", "direction": "WEAK"}},
    event={
        "evidence_grade": "A+",
        "action_eligibility": "ELIGIBLE",
        "status": "CONFIRMED",
    },
)

T5_ACCOUNT_UNKNOWN = _case(
    "T5",
    account_truth={"account": "UNKNOWN", "position": "KNOWN", "protection": "KNOWN"},
    trend={"btc": {"level": "L4/5", "direction": "BULL"}},
)

T6_CLOSE_WHILE_OPEN_BLOCKED = _case(
    "T6",
    close_condition=True,
    account_truth={"protection": "UNKNOWN"},
    trend={"btc": {"level": "L4/5", "direction": "BULL"}},
    current_state={
        "spot": {"btc": 80.0, "eth": 10.0, "usdt": 10.0},
        "overlay": {"btc": 15.0, "eth": 0.0},
        "event_increment_risk": 0.0,
    },
)

T7_EVENT_RETRACTED = _case(
    "T7",
    trend={"btc": {"level": "L4/5", "direction": "BULL"}},
    event={
        "evidence_grade": "E3",
        "action_eligibility": "ACTIVE",
        "status": "RETRACTED",
    },
    current_state={
        "spot": {"btc": 70.0, "eth": 20.0, "usdt": 10.0},
        "overlay": {"btc": 12.0, "eth": 0.0},
        "event_increment_risk": 0.0025,
    },
)

T8_STOP_OLD_EVIDENCE = _case(
    "T8",
    rearm={"disarmed": True, "evidence_epoch": 3, "last_disarm_epoch": 3},
    trend={"btc": {"level": "L4/5", "direction": "BULL"}},
)

T8_FRESH_EVIDENCE = _case(
    "T8_FRESH",
    rearm={"disarmed": True, "evidence_epoch": 4, "last_disarm_epoch": 3},
    trend={"btc": {"level": "L4/5", "direction": "BULL"}},
)

T9_PLAN_SNAPSHOT = {
    "market_snapshot_version": "m1",
    "account_snapshot_version": "a1",
    "position_version": "p1",
    "open_order_version": "o0",
    "policy_hash": "pol1",
    "strategy_hash": "str1",
}

T9_SUBMIT_SNAPSHOT_DRIFT = {
    "market_snapshot_version": "m1",
    "account_snapshot_version": "a2",
    "position_version": "p1",
    "open_order_version": "o0",
    "policy_hash": "pol1",
    "strategy_hash": "str1",
}

T10_PROTECTION_ACK_ONLY = {
    "proposed_stop": 95000.0,
    "approved_stop": 95000.0,
    "exchange_ack": True,
    "confirmed_active_stop": False,
}

ALL_T_CASES = [
    T1_ETH_CHEAP_L1,
    T2_BTC_L4_ETH_L4,
    T3_TREND_EVENT_SAME_DIR,
    T4_APLUS_EVENT_L1,
    T5_ACCOUNT_UNKNOWN,
    T6_CLOSE_WHILE_OPEN_BLOCKED,
    T7_EVENT_RETRACTED,
    T8_STOP_OLD_EVIDENCE,
]
