"""G0-4B 执行事实真源合同（离线 / FakeExchange，零出网）。

B1 保护数量真源：fills aggregate → 仓位事实；ACK.executedQty 不是 sizing。
B2 紧急平仓四态：ATTEMPTED / REJECTED / UNKNOWN / CONFIRMED；
   没有权威成交或仓位归零事实，永远不能 CONFIRMED。
B3 强制 SL 缺失 → OPEN DENIED；废除 99/101 哨兵；非法保护价不得提交。
"""
import inspect
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hypothesis import given, settings, strategies as st  # noqa: E402

from aurora.kernel.fake_exchange import FakeExchange  # noqa: E402
from aurora.kernel.ledger import Ledger, PositionFactState  # noqa: E402
from aurora.kernel.orchestrator import (  # noqa: E402
    EMERGENCY_CLOSE_CONFIRMED,
    EMERGENCY_CLOSE_REJECTED,
    EMERGENCY_CLOSE_UNKNOWN,
    EXECUTION_QTY_DRIFT,
    Orchestrator,
)
from aurora.kernel.port import OrderKind  # noqa: E402
from aurora.kernel.state_machine import IntentState  # noqa: E402


def _boot(ack_executed_qty=None, entry="ok", protection="ok", close="ok"):
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "ledger.db")
    exchange = FakeExchange(
        entry_behavior=entry, protection_behavior=protection, close_behavior=close)
    if ack_executed_qty is not None:
        exchange.ack_executed_qty = ack_executed_qty
    ledger = Ledger(path)
    orch = Orchestrator(ledger, exchange, instance_id="g04b")
    orch.recover()
    return tmp, path, exchange, ledger, orch


class ProtectionQuantityTruthTests(unittest.TestCase):
    def tearDown(self):
        if getattr(self, "ledger", None):
            self.ledger.close()
        if getattr(self, "_tmp", None):
            self._tmp.cleanup()

    def _open_incident_analogue(self):
        self._tmp, _, self.exchange, self.ledger, self.orch = _boot(
            ack_executed_qty=0.0)
        self.exchange.ack_executed_qty = 0.0
        return self.orch.open_position(
            "LONG", 0.007, intent_id="AURORA-0650a39f56e3",
            stop_price=99.0, take_profit_price=101.0)

    def test_ACK_ZERO_WITH_REAL_FILL(self):
        opened = self._open_incident_analogue()
        self.assertTrue(opened["success"], opened)
        entry = self.ledger.get_order("AURORA-0650a39f56e3-ENTRY")
        self.assertAlmostEqual(entry["filled_qty"], 0.007, places=10)
        fills = self.ledger.fills_aggregate("AURORA-0650a39f56e3-ENTRY")
        self.assertAlmostEqual(fills["qty"], 0.007, places=10)
        sl = [r for r in self.exchange.submit_log if r.order_kind == OrderKind.STOP_LOSS]
        self.assertEqual(len(sl), 1)
        self.assertAlmostEqual(sl[0].quantity, 0.007, places=10)
        self.assertNotAlmostEqual(sl[0].quantity, 0.0, places=10)

    def test_PROTECTION_USES_FILL_AGGREGATE(self):
        opened = self._open_incident_analogue()
        agg = self.ledger.fills_aggregate("AURORA-0650a39f56e3-ENTRY")["qty"]
        self.assertAlmostEqual(opened["protected_qty"], agg, places=10)
        sl = self.ledger.get_order("AURORA-0650a39f56e3-SL")
        self.assertAlmostEqual(sl["quantity"], agg, places=10)

    def test_ORDER_PROJECTION_CONVERGES(self):
        self._open_incident_analogue()
        entry = self.ledger.get_order("AURORA-0650a39f56e3-ENTRY")
        agg = self.ledger.fills_aggregate("AURORA-0650a39f56e3-ENTRY")["qty"]
        self.assertAlmostEqual(entry["filled_qty"], agg, places=10)
        self.assertEqual(entry["state"], "FILLED")

    def test_PROTECTION_QTY_NONZERO(self):
        opened = self._open_incident_analogue()
        self.assertGreater(opened["protected_qty"], 0.0)

    def test_PROTECTION_QTY_LE_POSITION(self):
        opened = self._open_incident_analogue()
        pos = self.exchange.position("BTCUSDT")
        self.assertLessEqual(opened["protected_qty"], abs(pos.signed_qty) + 1e-12)

    def test_HEDGE_REDUCTION_DIRECTION(self):
        self._tmp, _, self.exchange, self.ledger, self.orch = _boot()
        self.orch.open_position(
            "LONG", 0.007, intent_id="HEDGE-L",
            stop_price=99.0, take_profit_price=101.0)
        sl = [r for r in self.exchange.submit_log if r.order_kind == OrderKind.STOP_LOSS][0]
        self.assertEqual(sl.side, "SELL")
        self.assertEqual(sl.position_side, "LONG")
        self.ledger.close()
        self._tmp.cleanup()
        self._tmp, _, self.exchange, self.ledger, self.orch = _boot()
        self.orch.open_position(
            "SHORT", 0.007, intent_id="HEDGE-S",
            stop_price=101.0, take_profit_price=99.0)
        sl = [r for r in self.exchange.submit_log if r.order_kind == OrderKind.STOP_LOSS][0]
        self.assertEqual(sl.side, "BUY")
        self.assertEqual(sl.position_side, "SHORT")

    def test_execution_qty_drift_does_not_pick_min_or_max(self):
        self._tmp, _, self.exchange, self.ledger, self.orch = _boot()
        self.exchange.ack_executed_qty = 0.0
        self.exchange.seed_external_position(-0.002, 100.0, leg="LONG")
        opened = self.orch.open_position(
            "LONG", 0.007, intent_id="DRIFT",
            stop_price=99.0, take_profit_price=101.0)
        self.assertFalse(opened["success"])
        self.assertEqual(opened["reason"], EXECUTION_QTY_DRIFT)
        self.assertEqual(
            self.ledger.get_intent("DRIFT")["state"],
            IntentState.RECOVERY_REQUIRED.value)
        self.assertTrue(self.ledger.kill_state()["engaged"])
        sl = [r for r in self.exchange.submit_log if r.order_kind == OrderKind.STOP_LOSS]
        self.assertEqual(sl, [])
        self.assertFalse(
            self.orch.open_position(
                "LONG", 0.001, intent_id="AFTER-DRIFT",
                stop_price=99.0, take_profit_price=101.0)["success"])


class EmergencyCloseTruthTests(unittest.TestCase):
    def tearDown(self):
        if getattr(self, "ledger", None):
            self.ledger.close()
        if getattr(self, "_tmp", None):
            self._tmp.cleanup()

    def test_EMERGENCY_REJECTED_NOT_CONFIRMED(self):
        self._tmp, _, self.exchange, self.ledger, self.orch = _boot(
            protection="reject", close="reject")
        result = self.orch.open_position(
            "LONG", 0.007, intent_id="EM-R",
            stop_price=99.0, take_profit_price=101.0)
        self.assertFalse(result["success"])
        self.assertEqual(result.get("close_outcome"), "REJECTED")
        self.assertNotEqual(result.get("close_outcome"), "CONFIRMED")
        kill = self.ledger.kill_state()["reason"]
        self.assertIn(EMERGENCY_CLOSE_REJECTED, kill)
        self.assertNotIn(EMERGENCY_CLOSE_CONFIRMED, kill)
        self.assertNotIn("emergency close executed", kill)
        self.assertGreater(
            abs(self.exchange.position("BTCUSDT").signed_qty), 0.0)

    def test_EMERGENCY_UNKNOWN_NOT_CONFIRMED(self):
        self._tmp, _, self.exchange, self.ledger, self.orch = _boot(
            protection="reject", close="timeout_then_gone")
        result = self.orch.open_position(
            "LONG", 0.007, intent_id="EM-U",
            stop_price=99.0, take_profit_price=101.0)
        self.assertFalse(result["success"])
        self.assertEqual(result.get("close_outcome"), "UNKNOWN")
        self.assertNotEqual(result.get("close_outcome"), "CONFIRMED")
        kill = self.ledger.kill_state()["reason"]
        self.assertIn(EMERGENCY_CLOSE_UNKNOWN, kill)
        self.assertNotIn(EMERGENCY_CLOSE_CONFIRMED, kill)
        self.assertNotIn("emergency close executed", kill)

    def test_EMERGENCY_CONFIRMED_REQUIRES_FACT(self):
        self._tmp, _, self.exchange, self.ledger, self.orch = _boot(
            protection="reject", close="ok")
        result = self.orch.open_position(
            "LONG", 0.007, intent_id="EM-C",
            stop_price=99.0, take_profit_price=101.0)
        self.assertFalse(result["success"])
        self.assertEqual(result.get("close_outcome"), "CONFIRMED")
        close_cid = "EM-C-CLOSE-EMG"
        self.assertGreater(self.ledger.fills_aggregate(close_cid)["qty"], 0.0)
        self.assertAlmostEqual(
            abs(self.exchange.position("BTCUSDT").signed_qty), 0.0, places=10)
        kill = self.ledger.kill_state()["reason"]
        self.assertIn(EMERGENCY_CLOSE_CONFIRMED, kill)
        self.assertNotIn("emergency close executed", kill)

    def test_KILL_REASON_MATCHES_REALITY(self):
        self._tmp, _, self.exchange, self.ledger, self.orch = _boot(
            protection="reject", close="reject")
        result = self.orch.open_position(
            "LONG", 0.007, intent_id="EM-K",
            stop_price=99.0, take_profit_price=101.0)
        kill = self.ledger.kill_state()["reason"]
        self.assertIn(EMERGENCY_CLOSE_REJECTED, result["reason"])
        self.assertIn(EMERGENCY_CLOSE_REJECTED, kill)
        self.assertNotIn("executed", kill.lower())


class MandatoryProtectionInputTests(unittest.TestCase):
    def tearDown(self):
        if getattr(self, "ledger", None):
            self.ledger.close()
        if getattr(self, "_tmp", None):
            self._tmp.cleanup()

    def test_MISSING_SL_DENIES_ENTRY(self):
        self._tmp, _, self.exchange, self.ledger, self.orch = _boot()
        result = self.orch.open_position("LONG", 0.007, intent_id="NO-SL")
        self.assertFalse(result["success"])
        self.assertIn("OPEN DENIED", result["reason"])
        self.assertIsNone(self.ledger.get_intent("NO-SL"))
        self.assertEqual(self.exchange.submit_log, [])

    def test_NO_99_101_SENTINEL(self):
        src = inspect.getsource(Orchestrator._protect_prices)
        self.assertNotIn("99.0", src)
        self.assertNotIn("101.0", src)
        self._tmp, _, self.exchange, self.ledger, self.orch = _boot()
        self.orch.open_position(
            "LONG", 0.007, intent_id="NO-SENT",
            stop_price=95.0, take_profit_price=110.0)
        sl = [r for r in self.exchange.submit_log if r.order_kind == OrderKind.STOP_LOSS]
        tp = [r for r in self.exchange.submit_log if r.order_kind == OrderKind.TAKE_PROFIT]
        self.assertAlmostEqual(sl[0].stop_price, 95.0)
        self.assertAlmostEqual(tp[0].stop_price, 110.0)

    def test_INVALID_PROTECTION_PRICE_REJECTED(self):
        self._tmp, _, self.exchange, self.ledger, self.orch = _boot()
        for px in (None, 0, -1.0, float("nan"), float("inf")):
            with self.subTest(px=px):
                iid = f"BAD-{px}"
                result = self.orch.open_position(
                    "LONG", 0.007, intent_id=iid, stop_price=px,
                    take_profit_price=101.0)
                self.assertFalse(result["success"])
                self.assertIn("OPEN DENIED", result["reason"])
                self.assertIsNone(self.ledger.get_intent(iid))
                self.assertEqual(
                    [r for r in self.exchange.submit_log if r.order_kind == OrderKind.ENTRY],
                    [])
        result = self.orch.open_position(
            "LONG", 0.007, intent_id="REL-BAD",
            stop_price=101.0, take_profit_price=110.0)
        self.assertFalse(result["success"])
        sl = [r for r in self.exchange.submit_log if r.order_kind == OrderKind.STOP_LOSS]
        self.assertEqual(sl, [])

    def test_VALID_TP_NOT_CONFIGURED_ALLOWED(self):
        self._tmp, _, self.exchange, self.ledger, self.orch = _boot()
        opened = self.orch.open_position(
            "LONG", 0.007, intent_id="SL-ONLY",
            stop_price=99.0, take_profit_price=None)
        self.assertTrue(opened["success"], opened)
        self.assertTrue(opened.get("safe_but_incomplete"))
        tp = [r for r in self.exchange.submit_log if r.order_kind == OrderKind.TAKE_PROFIT]
        self.assertEqual(tp, [])
        sl = [r for r in self.exchange.submit_log if r.order_kind == OrderKind.STOP_LOSS]
        self.assertEqual(len(sl), 1)
        note = self.ledger.get_intent("SL-ONLY")["reason"]
        self.assertIn("NOT_CONFIGURED", note)


class G04BPropertyInvariants(unittest.TestCase):
    @settings(max_examples=25, deadline=None)
    @given(qty=st.floats(min_value=0.001, max_value=0.02, allow_nan=False,
                         allow_infinity=False))
    def test_ack_zero_never_sizes_protection_to_zero(self, qty):
        qty = round(qty, 3)
        if qty <= 0:
            return
        tmp, _, exchange, ledger, orch = _boot(ack_executed_qty=0.0)
        try:
            opened = orch.open_position(
                "LONG", qty, intent_id="P-ACK0",
                stop_price=99.0, take_profit_price=101.0)
            if not opened.get("success"):
                return
            agg = ledger.fills_aggregate("P-ACK0-ENTRY")["qty"]
            self.assertGreater(agg, 0.0)
            self.assertAlmostEqual(opened["protected_qty"], agg, places=8)
            self.assertGreater(opened["protected_qty"], 0.0)
        finally:
            ledger.close()
            tmp.cleanup()

    def test_no_authoritative_close_fact_never_confirmed(self):
        for close_b in ("reject", "timeout_then_gone"):
            with self.subTest(close=close_b):
                tmp, _, exchange, ledger, orch = _boot(
                    protection="reject", close=close_b)
                try:
                    result = orch.open_position(
                        "LONG", 0.007, intent_id="NO-FACT",
                        stop_price=99.0, take_profit_price=101.0)
                    self.assertNotEqual(result.get("close_outcome"), "CONFIRMED")
                    self.assertNotIn(
                        EMERGENCY_CLOSE_CONFIRMED,
                        ledger.kill_state()["reason"])
                    close_orders = [
                        r for r in exchange.submit_log if r.order_kind == OrderKind.CLOSE]
                    for req in close_orders:
                        self.assertEqual(
                            ledger.fills_aggregate(req.client_order_id)["qty"], 0.0)
                finally:
                    ledger.close()
                    tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
