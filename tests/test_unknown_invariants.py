"""G0-3：UNKNOWN 是一等执行状态——不得被静默降级为任何确定性结论。

总原则：UNKNOWN cannot create certainty。
- 无新的更强交易所事实，重复 recover/reconcile/超时/陈旧快照
  不能把 UNKNOWN 收敛成 REJECTED/FILLED/CANCELLED/FLAT/RECONCILED；
- UNKNOWN 阻断新增风险，但不锁死已批准的恢复/减仓通道；
- UNKNOWN 不产生财务事实（fills/pnl/fees 不因重试而增长）。
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hypothesis import given, settings, strategies as st  # noqa: E402

from aurora.kernel.fake_exchange import FakeExchange  # noqa: E402
from aurora.kernel.ledger import Ledger, PositionFactState  # noqa: E402
from aurora.kernel.orchestrator import Orchestrator  # noqa: E402
from aurora.kernel.port import OrderKind  # noqa: E402
from aurora.kernel.state_machine import IntentState  # noqa: E402
from tests.kernel_test_open import bind_explicit_protect_prices  # noqa: E402

TERMINAL_OR_CERTAIN = {
    "FILLED", "REJECTED", "CANCELLED",
    IntentState.RECONCILED.value, IntentState.CLOSED.value,
    IntentState.PROTECTED.value,
}


class Harness(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "ledger.db")
        self.exchange = FakeExchange()
        self.ledger = Ledger(self.path)
        self.orch = Orchestrator(self.ledger, self.exchange, instance_id="t")
        bind_explicit_protect_prices(self.orch)

    def tearDown(self):
        self.ledger.close()
        self._tmp.cleanup()

    def _boot_flat(self):
        self.orch.recover()
        self.assertEqual(
            self.ledger.get_position_fact("BTCUSDT")["state"],
            PositionFactState.KNOWN_FLAT.value)


class SubmitUnknownStabilityTests(Harness):
    def _submit_unknown(self):
        self._boot_flat()
        self.exchange.entry_behavior = "timeout_then_gone"
        r = self.orch.open_position("LONG", 0.01, intent_id="U1")
        self.assertEqual(r["state"], "SUBMIT_UNKNOWN")
        self.exchange.entry_behavior = "ok"

    def test_repeated_failed_queries_keep_unknown(self):
        self._submit_unknown()
        self.exchange._fail_order_query = True
        for _ in range(5):
            report = self.orch.recover()
            self.assertTrue(report["unresolved"])
            order = self.ledger.get_order("U1-ENTRY")
            self.assertEqual(order["state"], "SUBMIT_UNKNOWN")
            intent = self.ledger.get_intent("U1")
            self.assertNotIn(intent["state"], TERMINAL_OR_CERTAIN)

    def test_authoritative_not_found_then_rejected(self):
        self._submit_unknown()
        self.orch.recover()  # 权威查询：订单不存在 → REJECTED
        order = self.ledger.get_order("U1-ENTRY")
        self.assertEqual(order["state"], "REJECTED")
        self.assertEqual(
            self.ledger.get_intent("U1")["state"], IntentState.REJECTED.value)

    def test_no_financial_facts_while_unknown(self):
        self._submit_unknown()
        self.exchange._fail_order_query = True
        for _ in range(4):
            self.orch.recover()
        self.assertEqual(self.ledger.fills_for_order("U1-ENTRY"), [])


class CancelUnknownStabilityTests(Harness):
    def test_cancel_unknown_never_reconciles_without_evidence(self):
        self._boot_flat()
        self.orch.open_position("LONG", 0.01, intent_id="C1")
        self.exchange.fire_protection("C1-SL", price=99.0)
        self.exchange.cancel_behavior = "unknown"
        self.orch.recover()
        self.assertEqual(
            self.ledger.get_intent("C1")["state"],
            IntentState.RECOVERY_REQUIRED.value)
        self.assertTrue(self.ledger.kill_state()["engaged"])
        # 无新证据的重复恢复：不得自动收敛
        self.exchange._fail_order_query = True
        for _ in range(3):
            self.orch.recover()
            self.assertNotEqual(
                self.ledger.get_intent("C1")["state"],
                IntentState.RECONCILED.value)


class PositionAndProtectionUnknownTests(Harness):
    def test_position_query_failure_never_flat(self):
        self._boot_flat()
        self.orch.open_position("LONG", 0.01, intent_id="P1")
        self.exchange._fail_position = True
        self.orch.recover()
        fact = self.ledger.get_position_fact("BTCUSDT")
        self.assertNotEqual(fact["state"], PositionFactState.KNOWN_FLAT.value)
        self.assertEqual(fact["state"], PositionFactState.UNKNOWN.value)

    def test_protection_unverifiable_is_not_protected_nor_clean(self):
        # 保护证据查询不可用 → 不宣称 PROTECTED，也不宣称“确定无保护”。
        self._boot_flat()
        self.orch.open_position("LONG", 0.01, intent_id="P2")
        self.exchange._fail_order_query = True
        out = self.orch.sync_protection("P2")
        self.assertFalse(out.get("success"))
        intent = self.ledger.get_intent("P2")
        self.assertNotEqual(intent["state"], IntentState.RECONCILED.value)


class OpenGateAndRecoveryChannelTests(Harness):
    def test_unknown_blocks_new_risk_but_keeps_recovery_paths(self):
        self._boot_flat()
        self.orch.open_position("LONG", 0.01, intent_id="R1")
        self.exchange._fail_position = True
        self.orch.recover()
        # 新增风险被阻断
        self.assertFalse(self.orch.open_position("LONG", 0.01)["success"])
        # 已批准的恢复通道仍可用：恢复查询成功后 emergency close 不被 UNKNOWN 锁死
        self.exchange._fail_position = False
        self.orch.recover()
        res = self.orch.close_position("risk-off after recovery")
        self.assertTrue(res.get("success") or res.get("intent_id"))


class DuplicateEvidenceTests(Harness):
    def test_same_fill_twice_no_double_accounting(self):
        self._boot_flat()
        self.orch.open_position("LONG", 0.01, intent_id="D1")
        self.exchange.fire_protection("D1-SL", price=99.0)
        self.ledger.close()
        self.ledger = Ledger(self.path)
        self.orch = Orchestrator(self.ledger, self.exchange, instance_id="t2")
        self.orch.recover()
        self.orch.recover()  # 同一份迟到证据再次收敛
        fills = self.ledger.fills_for_order("D1-SL")
        self.assertEqual(len(fills), 1)
        self.assertEqual(
            self.ledger.get_intent("D1")["state"], IntentState.RECONCILED.value)


class HypothesisUnknownInvariants(Harness):
    """P1+P4：任意轮数无证据观察不产生确定性或财务事实。"""

    @settings(max_examples=20, deadline=None)
    @given(st.integers(min_value=1, max_value=8))
    def test_no_evidence_never_converges(self, rounds):
        self._submit_unknown_inner()
        self.exchange._fail_order_query = True
        for _ in range(rounds):
            report = self.orch.recover()
            self.assertTrue(report["unresolved"])
        order = self.ledger.get_order("H-ENTRY")
        self.assertEqual(order["state"], "SUBMIT_UNKNOWN")
        intent = self.ledger.get_intent("H")
        self.assertNotIn(intent["state"], TERMINAL_OR_CERTAIN)
        self.assertEqual(self.ledger.fills_for_order("H-ENTRY"), [])

    def _submit_unknown_inner(self):
        self._boot_flat()
        self.exchange.entry_behavior = "timeout_then_gone"
        self.orch.open_position("LONG", 0.01, intent_id="H")
        self.exchange.entry_behavior = "ok"

    @settings(max_examples=20, deadline=None)
    @given(st.integers(min_value=1, max_value=8))
    def test_unknown_blocks_new_opens_for_any_rounds(self, rounds):
        self._submit_unknown_inner()
        self.exchange._fail_order_query = True
        for _ in range(rounds):
            self.orch.recover()
            res = self.orch.open_position("SHORT", 0.02)
            self.assertFalse(res["success"])
            self.assertFalse(
                any(o.order_kind == OrderKind.ENTRY and o.side == "SELL"
                    for o in self.exchange.submit_log))


if __name__ == "__main__":
    unittest.main()
