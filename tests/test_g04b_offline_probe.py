"""G0-4B 验收附件：执行事实真源批次在零出网条件下验证（离线铁证）。

在 socket 层挂绊网（create_connection / connect / getaddrinfo 全部拒绝），
跑完事故复现 → 权威 sizing → 紧急平仓拒绝语义 → 重启恢复 主链。
任何真实 Binance 请求都会先触发绊网而不是到达交易所。
"""
import os
import socket
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.kernel.fake_exchange import FakeExchange  # noqa: E402
from aurora.kernel.ledger import Ledger  # noqa: E402
from aurora.kernel.orchestrator import Orchestrator  # noqa: E402
from aurora.kernel.port import OrderKind  # noqa: E402


def _refuse_network(*args, **kwargs):
    raise AssertionError("network call attempted during offline G0-4B probe")


class OfflineTripwireTests(unittest.TestCase):
    def setUp(self):
        self._patches = [
            mock.patch("socket.create_connection", side_effect=_refuse_network),
            mock.patch("socket.socket.connect", side_effect=_refuse_network),
            mock.patch("socket.getaddrinfo", side_effect=_refuse_network),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "ledger.db")

    def _boot(self, exchange):
        ledger = Ledger(self.path)
        orch = Orchestrator(ledger, exchange, instance_id="probe")
        orch.recover()
        return ledger, orch

    def test_full_g04b_chain_runs_without_any_network_call(self):
        # 事故复现：ACK executedQty=0 但真实成交 0.007
        exchange = FakeExchange(entry_behavior="ok")
        exchange.ack_executed_qty = 0.0
        ledger, orch = self._boot(exchange)

        opened = orch.open_position(
            "LONG", 0.007, intent_id="AURORA-G04B-PROBE",
            stop_price=99.0, take_profit_price=101.0)
        self.assertTrue(opened["success"], opened)
        self.assertEqual(opened["state"], "PROTECTED")
        self.assertAlmostEqual(opened["protected_qty"], 0.007, places=10)
        sl = [r for r in exchange.submit_log if r.order_kind == OrderKind.STOP_LOSS]
        self.assertEqual(len(sl), 1)
        self.assertAlmostEqual(sl[0].quantity, 0.007, places=10)
        ledger.close()

        # 重启恢复：同一账本、同一交易所事实、新内核实例，投影与保护可复算
        ledger2 = Ledger(self.path)
        orch2 = Orchestrator(ledger2, exchange, instance_id="probe-B")
        report = orch2.recover()
        self.assertEqual(
            ledger2.get_position_fact("BTCUSDT")["state"], "KNOWN_OPEN")
        self.assertNotIn("BOOT_DRIFT", [e.get("fact") for e in report["unresolved"]])
        # 权威聚合 = 订单投影 = 保护数量
        agg = ledger2.fills_aggregate("AURORA-G04B-PROBE-ENTRY")["qty"]
        self.assertAlmostEqual(agg, 0.007, places=10)
        self.assertAlmostEqual(
            ledger2.get_order("AURORA-G04B-PROBE-ENTRY")["filled_qty"], agg, places=10)
        ledger2.close()

    def test_emergency_rejected_kill_reason_states_reality_offline(self):
        exchange = FakeExchange(
            entry_behavior="ok", protection_behavior="reject", close_behavior="reject")
        ledger, orch = self._boot(exchange)
        result = orch.open_position(
            "LONG", 0.007, intent_id="AURORA-G04B-EMG",
            stop_price=99.0, take_profit_price=101.0)
        self.assertFalse(result["success"])
        self.assertTrue(result.get("halt"))
        kill = ledger.kill_state()
        self.assertEqual(kill["engaged"], 1)
        self.assertIn("EMERGENCY_CLOSE_REJECTED", kill["reason"])
        self.assertNotIn("executed", kill["reason"])
        # 紧急平仓被拒后不得有任何 CLOSE 成交事实被编造
        fills = ledger.fills_for_order("AURORA-G04B-EMG-CLOSE-EMG")
        self.assertEqual(fills, [])
        ledger.close()


if __name__ == "__main__":
    unittest.main()
