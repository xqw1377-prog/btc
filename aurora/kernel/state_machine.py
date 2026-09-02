"""Intent 生命周期状态机（P0-B1）。

合法路径：
INTENT_CREATED → SUBMITTING → (ACKNOWLEDGED | PARTIALLY_FILLED) → FILLED_UNPROTECTED
→ PROTECTION_SUBMITTING → PROTECTED → CLOSING → CLOSED → RECONCILED

异常路径：REJECTED / SUBMIT_UNKNOWN / PROTECTION_FAILED / CLOSE_UNKNOWN / RECOVERY_REQUIRED

铁律：
- SUBMIT_UNKNOWN 禁止自动重提；必须先按 client_order_id 查询事实（P0-B1 门禁）。
- 每次状态转移必须带时间、原因与关联 ID（由 ledger 落账，本模块只做校验）。
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, FrozenSet, Optional


class IntentState(str, Enum):
    INTENT_CREATED = "INTENT_CREATED"
    SUBMITTING = "SUBMITTING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED_UNPROTECTED = "FILLED_UNPROTECTED"
    PROTECTION_SUBMITTING = "PROTECTION_SUBMITTING"
    PROTECTED = "PROTECTED"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"
    RECONCILED = "RECONCILED"
    REJECTED = "REJECTED"
    SUBMIT_UNKNOWN = "SUBMIT_UNKNOWN"
    PROTECTION_FAILED = "PROTECTION_FAILED"
    CLOSE_UNKNOWN = "CLOSE_UNKNOWN"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


ALLOWED_TRANSITIONS: Dict[IntentState, FrozenSet[IntentState]] = {
    IntentState.INTENT_CREATED: frozenset({IntentState.SUBMITTING, IntentState.REJECTED}),
    IntentState.SUBMITTING: frozenset({
        IntentState.ACKNOWLEDGED,
        IntentState.PARTIALLY_FILLED,
        IntentState.FILLED_UNPROTECTED,
        IntentState.SUBMIT_UNKNOWN,
        IntentState.REJECTED,
        # 仅限 CLOSE 意图：开仓链路之外的平仓意图直接进入平仓段
        IntentState.CLOSING,
    }),
    # SUBMIT_UNKNOWN 只能经由"按 client_order_id 查询事实"离开，禁止回到 SUBMITTING
    IntentState.SUBMIT_UNKNOWN: frozenset({
        IntentState.ACKNOWLEDGED,
        IntentState.PARTIALLY_FILLED,
        IntentState.FILLED_UNPROTECTED,
        IntentState.REJECTED,
    }),
    IntentState.ACKNOWLEDGED: frozenset({
        IntentState.PARTIALLY_FILLED,
        IntentState.FILLED_UNPROTECTED,
    }),
    IntentState.PARTIALLY_FILLED: frozenset({
        IntentState.FILLED_UNPROTECTED,
        IntentState.PROTECTION_SUBMITTING,
    }),
    IntentState.FILLED_UNPROTECTED: frozenset({
        IntentState.PROTECTION_SUBMITTING,
        IntentState.PROTECTION_FAILED,
    }),
    IntentState.PROTECTION_SUBMITTING: frozenset({
        IntentState.PROTECTED,
        IntentState.PROTECTION_FAILED,
    }),
    IntentState.PROTECTED: frozenset({IntentState.CLOSING}),
    IntentState.PROTECTION_FAILED: frozenset({IntentState.CLOSING}),
    IntentState.CLOSING: frozenset({IntentState.CLOSED, IntentState.CLOSE_UNKNOWN}),
    IntentState.CLOSE_UNKNOWN: frozenset({IntentState.CLOSED, IntentState.RECOVERY_REQUIRED}),
    IntentState.CLOSED: frozenset({IntentState.RECONCILED}),
    IntentState.RECOVERY_REQUIRED: frozenset({IntentState.CLOSING, IntentState.RECONCILED}),
    IntentState.REJECTED: frozenset(),
    IntentState.RECONCILED: frozenset(),
}


class InvalidTransition(Exception):
    pass


@dataclass(frozen=True)
class Transition:
    entity_type: str
    entity_id: str
    from_state: str
    to_state: str
    at: str
    reason: str
    correlation_id: str

    def __post_init__(self):
        if not self.reason:
            raise InvalidTransition("transition without reason")
        if not self.correlation_id:
            raise InvalidTransition("transition without correlation id")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def assert_transition(
    entity_type: str,
    entity_id: str,
    from_state: IntentState,
    to_state: IntentState,
    reason: str,
    correlation_id: Optional[str] = None,
) -> Transition:
    if to_state not in ALLOWED_TRANSITIONS.get(from_state, frozenset()):
        raise InvalidTransition(
            f"{entity_type} {entity_id}: illegal transition {from_state.value} -> {to_state.value}"
        )
    return Transition(
        entity_type=entity_type,
        entity_id=entity_id,
        from_state=from_state.value,
        to_state=to_state.value,
        at=utc_now(),
        reason=reason,
        correlation_id=correlation_id or entity_id,
    )
