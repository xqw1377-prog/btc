"""P0-B1 账本测试：持久化、幂等、原子抢占、重启恢复。"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.kernel.ledger import Ledger, PositionFactState  # noqa: E402
from aurora.kernel.state_machine import IntentState  # noqa: E402


class LedgerHarness(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "ledger.db")
        self.ledger = Ledger(self.path)

    def tearDown(self):
        self.ledger.close()
        self._tmp.cleanup()


class DurabilityTests(LedgerHarness):
    def test_intent_survives_reopen(self):
        self.ledger.create_intent("A1", "BTCUSDT", "LONG", 0.01)
        self.ledger.transition_intent("A1", IntentState.SUBMITTING, "test")
        self.ledger.close()
        reopened = Ledger(self.path)
        intent = reopened.get_intent("A1")
        self.assertEqual(intent["state"], IntentState.SUBMITTING.value)
        reopened.close()

    def test_kill_switch_survives_reopen(self):
        self.ledger.engage_kill("daily loss")
        self.ledger.close()
        reopened = Ledger(self.path)
        kill = reopened.kill_state()
        self.assertTrue(kill["engaged"])
        self.assertEqual(kill["reason"], "daily loss")
        reopened.close()

    def test_pending_orders_recovered_after_reopen(self):
        self.ledger.create_intent("A1", "BTCUSDT", "LONG", 0.01)
        self.ledger.record_order_submitting(
            "A1-ENTRY", "A1", "ENTRY", "BUY", "LONG", 0.01)
        self.ledger.update_order("A1-ENTRY", state="SUBMIT_UNKNOWN")
        self.ledger.close()
        reopened = Ledger(self.path)
        pending = reopened.pending_orders()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["state"], "SUBMIT_UNKNOWN")
        reopened.close()


class IdempotencyTests(LedgerHarness):
    def test_duplicate_intent_create_returns_false(self):
        self.assertTrue(self.ledger.create_intent("A1", "BTCUSDT", "LONG", 0.01))
        self.assertFalse(self.ledger.create_intent("A1", "BTCUSDT", "LONG", 0.01))

    def test_duplicate_fill_not_double_counted(self):
        self.ledger.create_intent("A1", "BTCUSDT", "LONG", 0.01)
        self.ledger.record_order_submitting(
            "A1-ENTRY", "A1", "ENTRY", "BUY", "LONG", 0.01)
        first = self.ledger.insert_fill("F1", "A1-ENTRY", 0.01, 100.0, 0.0, "BUY", "t1")
        second = self.ledger.insert_fill("F1", "A1-ENTRY", 0.01, 100.0, 0.0, "BUY", "t1")
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(len(self.ledger.fills_for_order("A1-ENTRY")), 1)


class ClaimTests(LedgerHarness):
    def test_claim_exclusive_between_executors(self):
        self.ledger.create_intent("A1", "BTCUSDT", "LONG", 0.01)
        self.assertTrue(self.ledger.claim_intent("A1", "executor-A"))
        # 第二个执行器（不同实例）不能消费同一 Intent
        self.assertFalse(self.ledger.claim_intent("A1", "executor-B"))
        # 同一实例重复认领幂等
        self.assertTrue(self.ledger.claim_intent("A1", "executor-A"))

    def test_claim_fails_after_state_moved_on(self):
        self.ledger.create_intent("A1", "BTCUSDT", "LONG", 0.01)
        self.ledger.transition_intent("A1", IntentState.SUBMITTING, "moved on")
        self.assertFalse(self.ledger.claim_intent("A1", "executor-A"))


class TransitionAuditTests(LedgerHarness):
    def test_transitions_carry_time_reason_correlation(self):
        self.ledger.create_intent("A1", "BTCUSDT", "LONG", 0.01)
        self.ledger.transition_intent("A1", IntentState.SUBMITTING, "submit", "A1")
        self.ledger.transition_intent("A1", IntentState.SUBMIT_UNKNOWN, "timeout", "A1")
        rows = self.ledger.transitions_for("A1")
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertTrue(row["at"])
            self.assertTrue(row["reason"])
            self.assertEqual(row["correlation_id"], "A1")

    def test_position_fact_upsert(self):
        self.ledger.set_position_fact("BTCUSDT", PositionFactState.UNKNOWN, source="t")
        self.assertEqual(
            self.ledger.get_position_fact("BTCUSDT")["state"], PositionFactState.UNKNOWN.value)
        self.ledger.set_position_fact(
            "BTCUSDT", PositionFactState.KNOWN_OPEN, qty=0.01, side="LONG", source="t")
        fact = self.ledger.get_position_fact("BTCUSDT")
        self.assertEqual(fact["state"], PositionFactState.KNOWN_OPEN.value)
        self.assertEqual(fact["qty"], 0.01)


if __name__ == "__main__":
    unittest.main()
