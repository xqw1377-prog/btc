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
    PROTECTION_DEGRADED = "PROTECTION_DEGRADED"
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
        IntentState.RECOVERY_REQUIRED,
    }),
    IntentState.FILLED_UNPROTECTED: frozenset({
        IntentState.PROTECTION_SUBMITTING,
        IntentState.PROTECTION_FAILED,
        IntentState.RECOVERY_REQUIRED,
    }),
    IntentState.PROTECTION_SUBMITTING: frozenset({
        IntentState.PROTECTED,
        IntentState.PROTECTION_FAILED,
        IntentState.RECOVERY_REQUIRED,
    }),
    IntentState.PROTECTED: frozenset({
        IntentState.CLOSING,
        IntentState.PROTECTION_DEGRADED,
        IntentState.RECOVERY_REQUIRED,
    }),
    # 保护腿部分成交：仓位有剩余且保护覆盖不足，进入修复流程
    IntentState.PROTECTION_DEGRADED: frozenset({
        IntentState.PROTECTION_SUBMITTING,
        IntentState.RECOVERY_REQUIRED,
        IntentState.CLOSING,
    }),
    IntentState.PROTECTION_FAILED: frozenset({IntentState.CLOSING}),
    IntentState.CLOSING: frozenset({IntentState.CLOSED, IntentState.CLOSE_UNKNOWN}),
    IntentState.CLOSE_UNKNOWN: frozenset({IntentState.CLOSED, IntentState.RECOVERY_REQUIRED}),
    IntentState.CLOSED: frozenset({
        IntentState.RECONCILED,
        # 终态逃逸边：仅"迟到交易所事实"路径可用
        IntentState.RECOVERY_REQUIRED,
    }),
    IntentState.RECOVERY_REQUIRED: frozenset({IntentState.CLOSING, IntentState.RECONCILED}),
    # 终态逃逸边：仅允许"迟到交易所事实推翻本地终态"这一种路径使用
    IntentState.REJECTED: frozenset({IntentState.RECOVERY_REQUIRED}),
    IntentState.RECONCILED: frozenset({IntentState.RECOVERY_REQUIRED}),
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


TERMINAL_ESCAPE_SOURCES = (
    IntentState.RECONCILED,
    IntentState.REJECTED,
    IntentState.CLOSED,
)


def assert_transition(
    entity_type: str,
    entity_id: str,
    from_state: IntentState,
    to_state: IntentState,
    reason: str,
    correlation_id: Optional[str] = None,
    exchange_fact: Optional[tuple] = None,
) -> Transition:
    if to_state not in ALLOWED_TRANSITIONS.get(from_state, frozenset()):
        raise InvalidTransition(
            f"{entity_type} {entity_id}: illegal transition {from_state.value} -> {to_state.value}"
        )
    if (
        from_state in TERMINAL_ESCAPE_SOURCES
        and to_state == IntentState.RECOVERY_REQUIRED
    ):
        # 终态逃逸边仅限"交易所事实修正"：必须同时给出 fact_id 与 venue_fill_id，
        # 防止普通异常路径滥用该边推翻终态
        if not exchange_fact or not exchange_fact[0] or not exchange_fact[1]:
            raise InvalidTransition(
                f"{entity_type} {entity_id}: terminal escape "
                f"{from_state.value} -> RECOVERY_REQUIRED requires "
                f"exchange_fact=(fact_id, venue_fill_id)"
            )
        if not reason.startswith("EXCHANGE_FACT_CORRECTION"):
            raise InvalidTransition(
                f"{entity_type} {entity_id}: terminal escape reason must start "
                f"with EXCHANGE_FACT_CORRECTION"
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
