"""G0-4A 事故合同（离线 / fake transport）。

A. ObservedPositionMode 必须注入，缺失或不一致 FAIL CLOSED。
B. 减仓不得扩大风险：HEDGE 方向 + 数量；reduceOnly 不是唯一安全机制。
C. Algo 终态 ≠ fill（见 test_p0c_gates / test_binance_exchange）。
D. KNOWN_FLAT 允许 CLOSE_PROVENANCE_UNKNOWN；禁止补造 SELL/fee/pnl。
   证据残留不是永久开仓禁令；事故运行锁（kill / INCIDENT_LOCKED）另层决定。
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.armed_runtime import ArmedRuntime  # noqa: E402
from aurora.kernel.binance_exchange import BinanceExchange  # noqa: E402
from aurora.kernel.fake_exchange import FakeExchange  # noqa: E402
from aurora.kernel.ledger import CLOSE_PROVENANCE_UNKNOWN, Ledger, PositionFactState  # noqa: E402
from aurora.kernel.orchestrator import Orchestrator  # noqa: E402
from aurora.kernel.state_machine import IntentState  # noqa: E402
from aurora.p0_boundary import RunMode, SafetyViolation  # noqa: E402
from tests.test_binance_exchange import RecordingClient  # noqa: E402


class PositionModeInjectionTests(unittest.TestCase):
    def test_mutating_adapter_has_no_mode_default(self):
        with self.assertRaises(SafetyViolation) as ctx:
            BinanceExchange(RecordingClient(), allow_mutate=True)
        self.assertIn("ObservedPositionMode", str(ctx.exception))

    def test_runtime_observe_then_inject_never_defaults_one_way(self):
        client = RecordingClient()
        client.dual_side = "true"
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
                os.environ, {"AURORA_EXPECTED_POSITION_MODE": "HEDGE"}):
            rt = ArmedRuntime.attach(
                RunMode.TESTNET, client, os.path.join(tmp, "l.db"))
            try:
                self.assertEqual(rt.exchange.position_mode, "HEDGE")
                self.assertNotEqual(rt.exchange.position_mode, "ONE_WAY")
            finally:
                rt.close()


class CloseProvenanceUnknownTests(unittest.TestCase):
    def test_incident_analogue_flat_without_sell_fill(self):
        """EXIT-PROVENANCE-01：0.007 → 0，无匹配 userTrade/allOrder。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ledger.db")
            exchange = FakeExchange()
            ledger = Ledger(path)
            orch = Orchestrator(ledger, exchange, instance_id="g04a")
            try:
                orch.recover()
                opened = orch.open_position("LONG", 0.007, intent_id="AURORA-0650a39f56e3")
                self.assertTrue(opened["success"])
                exchange.flatten_without_fill()
                report = orch.recover()
                fact = ledger.get_position_fact("BTCUSDT")
                self.assertEqual(fact["state"], PositionFactState.KNOWN_FLAT.value)
                self.assertEqual(fact["source"], CLOSE_PROVENANCE_UNKNOWN)
                self.assertTrue(
                    any(e.get("fact") == CLOSE_PROVENANCE_UNKNOWN
                        for e in report["unresolved"]))
                self.assertNotEqual(
                    ledger.get_intent("AURORA-0650a39f56e3")["state"],
                    IntentState.RECONCILED.value)
                sell_fills = [
                    f for f in ledger.fills_for_order("AURORA-0650a39f56e3-ENTRY")
                    if f["side"] == "SELL"
                ]
                self.assertEqual(sell_fills, [])
                for order in ledger.orders_for_intent("AURORA-0650a39f56e3"):
                    if order["order_kind"] == "CLOSE":
                        self.fail("must not fabricate a CLOSE order")
                    for fill in ledger.fills_for_order(order["client_order_id"]):
                        self.assertNotEqual(fill["side"], "SELL")
                        self.assertFalse(fill.get("synthetic"))
                self.assertFalse(ledger.kill_state()["engaged"])
            finally:
                ledger.close()

    def test_provenance_residual_is_not_a_perpetual_kernel_open_ban(self):
        """证据残留可永久 OPEN；kill 未合上且仓位 KNOWN_FLAT 时内核允许新开。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ledger.db")
            exchange = FakeExchange()
            ledger = Ledger(path)
            orch = Orchestrator(ledger, exchange, instance_id="g04a")
            try:
                ledger.set_position_fact(
                    "BTCUSDT", PositionFactState.KNOWN_OPEN,
                    qty=0.007, side="LONG", source="test")
                report = orch.recover()
                self.assertTrue(
                    any(e.get("fact") == CLOSE_PROVENANCE_UNKNOWN
                        for e in report["unresolved"]))
                self.assertFalse(ledger.kill_state()["engaged"])
                opened = orch.open_position("LONG", 0.007, intent_id="NEXT")
                self.assertTrue(opened.get("success"))
            finally:
                ledger.close()

    def test_repeated_recover_preserves_not_found_does_not_synthesize(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ledger.db")
            exchange = FakeExchange()
            ledger = Ledger(path)
            orch = Orchestrator(ledger, exchange, instance_id="g04a")
            try:
                orch.recover()
                orch.open_position("LONG", 0.007, intent_id="EXIT01")
                exchange.flatten_without_fill()
                fill_count = None
                for _ in range(3):
                    report = orch.recover()
                    self.assertEqual(
                        ledger.get_position_fact("BTCUSDT")["state"],
                        PositionFactState.KNOWN_FLAT.value)
                    self.assertTrue(report["unresolved"])
                    all_fills = []
                    for order in ledger.orders_for_intent("EXIT01"):
                        all_fills.extend(ledger.fills_for_order(order["client_order_id"]))
                    if fill_count is None:
                        fill_count = len(all_fills)
                    else:
                        self.assertEqual(len(all_fills), fill_count)
                    self.assertFalse(any(f["side"] == "SELL" for f in all_fills))
            finally:
                ledger.close()


if __name__ == "__main__":
    unittest.main()
