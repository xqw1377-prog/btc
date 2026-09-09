"""T3-R1: FINAL RECOVERY CONVERGENCE 黑盒回归。

验证 G3 收敛门：
- OPEN + PROTECTED
- N cycles
- 独立 CLOSE 成交
- 交易所确认 flat
- 无未决订单/保护
- recover() 之后 active_recovery_required = FALSE

即使原始 PROTECTED intent 的 SL/TP 没有触发，也不应被拖入
RECOVERY_REQUIRED 作为 active recovery。
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.kernel.fake_exchange import FakeExchange
from aurora.kernel.ledger import Ledger, PositionFactState
from aurora.kernel.orchestrator import Orchestrator
from aurora.kernel.state_machine import IntentState
from tests.kernel_test_open import bind_explicit_protect_prices


class T3R1ConvergenceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "ledger.db")
        self.exchange = FakeExchange()
        self.ledger = Ledger(self.path)
        self.orch = bind_explicit_protect_prices(
            Orchestrator(self.ledger, self.exchange, instance_id="t3-r1"),
            stop_price=99.0, take_profit_price=101.0,
        )

    def tearDown(self):
        self.ledger.close()
        self._tmp.cleanup()

    def _no_unresolved_recovery(self, report):
        return [
            e for e in report["unresolved"]
            if e.get("fact") == "RECOVERY_REQUIRED"
            or e.get("fact") == "RECOVERY_REQUIRED"
        ]

    def test_full_lifecycle_converges_without_stranding_protected_intent(self):
        """G3: 独立 close 成交后，原始 PROTECTED intent 必须 converge 到 RECONCILED。"""
        # BOOT-DRIFT：先 recover() 建立 KNOWN_FLAT，才允许开仓
        self.orch.recover()
        opened = self.orch.open_position(
            "LONG", 0.001, intent_id="T3R1-OPEN", reason="T3-R1 entry")
        self.assertEqual(opened["state"], "PROTECTED")

        # N cycles: HOLD（不做任何动作）
        for _ in range(3):
            report = self.orch.recover()
            self.assertFalse(self._no_unresolved_recovery(report))

        # session end：用独立 close intent 平仓
        closed = self.orch.close_position(
            reason="T3-R1 session end", intent_id="T3R1-CLOSE")
        self.assertEqual(closed["state"], "RECONCILED")

        # 最终 recover
        report = self.orch.recover()

        # 关键断言：active recovery 必须为空
        self.assertFalse(self._no_unresolved_recovery(report))

        # 两个 intent 都应该是终态
        open_intent = self.ledger.get_intent("T3R1-OPEN")
        close_intent = self.ledger.get_intent("T3R1-CLOSE")
        self.assertEqual(open_intent["state"], IntentState.RECONCILED.value)
        self.assertEqual(close_intent["state"], IntentState.RECONCILED.value)

        # 仓位事实收敛到 KNOWN_FLAT
        fact = self.ledger.get_position_fact("BTCUSDT")
        self.assertEqual(fact["state"], PositionFactState.KNOWN_FLAT.value)
        self.assertEqual(fact["source"], "INDEPENDENT_CLOSE")

        # 无未决订单、无孤儿保护、无 kill
        self.assertEqual(self.ledger.pending_orders(), [])
        self.assertEqual(self.ledger.list_intents(states=[
            IntentState.SUBMITTING.value,
            IntentState.PROTECTION_SUBMITTING.value,
            IntentState.PROTECTED.value,
            IntentState.RECOVERY_REQUIRED.value,
        ]), [])
        self.assertFalse(self.ledger.kill_state()["engaged"])


if __name__ == "__main__":
    unittest.main()
