import os
import sys
import tempfile
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.execution_truth import (
    DurableExecutor,
    FakeExchange,
    IntentState,
    Ledger,
    OrderStatus,
    PositionState,
    Side,
)


class P0B2ProtectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "truth.db")
        self.ledger = Ledger(self.db_path)
        self.port = FakeExchange(symbol="BTCUSDT", default_price=Decimal("100000.00"), fee_rate=Decimal("0.0005"))
        self.executor = DurableExecutor(
            "BTCUSDT",
            self.ledger,
            self.port,
            max_retries=2,
            poll_interval_ms=0,
            poll_timeout_ms=0,
        )

    def tearDown(self):
        try:
            self.ledger._conn().close()
            del self.ledger._local.conn
        except Exception:
            pass
        self.tmp.cleanup()

    def test_open_with_stop_and_take_protection_succeeds(self):
        result = self.executor.open_position(
            Side.LONG,
            Decimal("0.1"),
            stop_loss=Decimal("99000.00"),
            take_profit=Decimal("110000.00"),
        )
        self.assertTrue(result["success"])

        position = self.ledger.get_position("BTCUSDT")
        self.assertEqual(position.state, PositionState.KNOWN_OPEN)
        self.assertIsNotNone(position.sl_order_id)
        self.assertIsNotNone(position.tp_order_id)

        sl = self.ledger.get_order(position.sl_order_id)
        tp = self.ledger.get_order(position.tp_order_id)
        self.assertEqual(sl.status, OrderStatus.ACKED)
        self.assertEqual(sl.order_type, "STOP_MARKET")
        self.assertEqual(tp.status, OrderStatus.ACKED)
        self.assertEqual(tp.order_type, "TAKE_PROFIT_MARKET")

    def test_close_cancels_open_protections(self):
        self.executor.open_position(
            Side.LONG,
            Decimal("0.1"),
            stop_loss=Decimal("99000.00"),
            take_profit=Decimal("110000.00"),
        )
        self.executor.close_position()

        position = self.ledger.get_position("BTCUSDT")
        self.assertEqual(position.state, PositionState.KNOWN_FLAT)
        self.assertEqual(len(self.port.cancel_calls), 2)

    def test_protection_submit_unknown_triggers_emergency_flatten(self):
        self.port.submit_unknown_type_once("STOP_MARKET")
        result = self.executor.open_position(
            Side.LONG,
            Decimal("0.1"),
            stop_loss=Decimal("99000.00"),
            take_profit=Decimal("110000.00"),
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "protection handshake failed")

        # System must have attempted to flatten the open
        position = self.ledger.get_position("BTCUSDT")
        self.assertEqual(position.state, PositionState.KNOWN_FLAT)

        intent = self.ledger._conn().execute(
            "SELECT state FROM intents WHERE intent_type=? ORDER BY created_at DESC LIMIT 1",
            ("OPEN",),
        ).fetchone()
        self.assertEqual(intent[0], IntentState.FAILED.value)

    def test_protection_explicit_fail_triggers_emergency_flatten(self):
        self.port.fail_type_once("STOP_MARKET")
        result = self.executor.open_position(
            Side.LONG,
            Decimal("0.1"),
            stop_loss=Decimal("99000.00"),
            take_profit=Decimal("110000.00"),
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "protection handshake failed")
        self.assertEqual(self.ledger.get_position("BTCUSDT").state, PositionState.KNOWN_FLAT)

    def test_open_without_protection_still_works(self):
        result = self.executor.open_position(Side.LONG, Decimal("0.1"))
        self.assertTrue(result["success"])
        self.assertIsNone(self.ledger.get_position("BTCUSDT").sl_order_id)
        self.assertIsNone(self.ledger.get_position("BTCUSDT").tp_order_id)


if __name__ == "__main__":
    unittest.main()
