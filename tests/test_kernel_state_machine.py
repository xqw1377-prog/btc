"""P0-B1 状态机测试：合法链路、异常路径、非法转移拒绝。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.kernel.state_machine import (  # noqa: E402
    ALLOWED_TRANSITIONS,
    IntentState,
    InvalidTransition,
    assert_transition,
)


class StateMachineTests(unittest.TestCase):
    def test_canonical_chain_is_legal(self):
        chain = [
            IntentState.INTENT_CREATED,
            IntentState.SUBMITTING,
            IntentState.FILLED_UNPROTECTED,
            IntentState.PROTECTION_SUBMITTING,
            IntentState.PROTECTED,
            IntentState.CLOSING,
            IntentState.CLOSED,
            IntentState.RECONCILED,
        ]
        for frm, to in zip(chain, chain[1:]):
            assert_transition("intent", "T", frm, to, "chain step", "T")

    def test_partial_fill_chain_is_legal(self):
        chain = [
            IntentState.SUBMITTING,
            IntentState.PARTIALLY_FILLED,
            IntentState.FILLED_UNPROTECTED,
            IntentState.PROTECTION_SUBMITTING,
        ]
        for frm, to in zip(chain, chain[1:]):
            assert_transition("intent", "T", frm, to, "partial chain", "T")

    def test_abnormal_paths_are_legal(self):
        legal = [
            (IntentState.SUBMITTING, IntentState.SUBMIT_UNKNOWN),
            (IntentState.SUBMIT_UNKNOWN, IntentState.FILLED_UNPROTECTED),
            (IntentState.SUBMIT_UNKNOWN, IntentState.REJECTED),
            (IntentState.FILLED_UNPROTECTED, IntentState.PROTECTION_FAILED),
            (IntentState.PROTECTION_SUBMITTING, IntentState.PROTECTION_FAILED),
            (IntentState.PROTECTION_FAILED, IntentState.CLOSING),
            (IntentState.CLOSING, IntentState.CLOSE_UNKNOWN),
            (IntentState.CLOSE_UNKNOWN, IntentState.RECOVERY_REQUIRED),
            (IntentState.CLOSE_UNKNOWN, IntentState.CLOSED),
            (IntentState.RECOVERY_REQUIRED, IntentState.RECONCILED),
            (IntentState.INTENT_CREATED, IntentState.REJECTED),
        ]
        for frm, to in legal:
            assert_transition("intent", "T", frm, to, "abnormal legal", "T")

    def test_submit_unknown_cannot_resubmit(self):
        """SUBMIT_UNKNOWN 禁止回到 SUBMITTING（自动重提被状态机物理封死）。"""
        self.assertNotIn(
            IntentState.SUBMITTING, ALLOWED_TRANSITIONS[IntentState.SUBMIT_UNKNOWN]
        )
        with self.assertRaises(InvalidTransition):
            assert_transition(
                "intent", "T", IntentState.SUBMIT_UNKNOWN, IntentState.SUBMITTING, "x", "T")

    def test_terminal_states_frozen_except_late_fact_escape(self):
        """终态封闭，唯一例外：迟到交易所事实 → RECOVERY_REQUIRED 逃逸边。"""
        for terminal, allowed_expected in (
            (IntentState.REJECTED, {IntentState.RECOVERY_REQUIRED}),
            (IntentState.RECONCILED, {IntentState.RECOVERY_REQUIRED}),
            (IntentState.CLOSED,
             {IntentState.RECONCILED, IntentState.RECOVERY_REQUIRED}),
        ):
            allowed = ALLOWED_TRANSITIONS[terminal]
            self.assertTrue(allowed <= allowed_expected, f"{terminal}: {allowed}")
            for target in IntentState:
                if target in allowed:
                    continue
                with self.assertRaises(InvalidTransition):
                    assert_transition("intent", "T", terminal, target, "x", "T")

    def test_protection_degraded_chain_is_legal(self):
        chain = [
            IntentState.PROTECTED,
            IntentState.PROTECTION_DEGRADED,
            IntentState.PROTECTION_SUBMITTING,
            IntentState.PROTECTED,
        ]
        for frm, to in zip(chain, chain[1:]):
            assert_transition("intent", "T", frm, to, "degraded repair", "T")
        # 降级态可直接进入恢复或紧急平仓
        assert_transition(
            "intent", "T", IntentState.PROTECTION_DEGRADED,
            IntentState.RECOVERY_REQUIRED, "cancel unknown", "T")
        assert_transition(
            "intent", "T", IntentState.PROTECTION_DEGRADED,
            IntentState.CLOSING, "repair failed", "T")

    def test_illegal_jump_rejected(self):
        illegal = [
            (IntentState.INTENT_CREATED, IntentState.PROTECTED),
            (IntentState.SUBMITTING, IntentState.CLOSED),
            (IntentState.PROTECTED, IntentState.RECONCILED),
            (IntentState.RECONCILED, IntentState.SUBMITTING),
        ]
        for frm, to in illegal:
            with self.assertRaises(InvalidTransition):
                assert_transition("intent", "T", frm, to, "x", "T")

    def test_transition_requires_reason_and_correlation(self):
        with self.assertRaises(InvalidTransition):
            assert_transition(
                "intent", "T", IntentState.INTENT_CREATED, IntentState.SUBMITTING, "", "T")
        # correlation 缺省回退到实体 ID，绝不留空
        transition = assert_transition(
            "intent", "T", IntentState.INTENT_CREATED, IntentState.SUBMITTING, "r", "")
        self.assertEqual(transition.correlation_id, "T")


if __name__ == "__main__":
    unittest.main()
