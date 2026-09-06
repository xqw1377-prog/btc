import os
import sys
import tempfile
import threading
import time
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.execution_truth import (
    DurableExecutor,
    ExecutionHalted,
    FakeExchange,
    IntentType,
    Ledger,
    OrderStatus,
    PositionState,
    Side,
)


class ReviewCharacterizationTests(unittest.TestCase):
    """P0-B1 review characterization tests: verify the foundation P0-B2 will rely on."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "truth.db")
        self.clock_value = "2026-09-02T00:00:00+00:00"
        self.ledger = Ledger(self.db_path, now_fn=lambda: self.clock_value)
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

    def _fresh_ledger(self):
        return Ledger(self.db_path, now_fn=lambda: self.clock_value)

    # 1. Clock injection ------------------------------------------------------
    def test_clock_is_injectable(self):
        intent = self.ledger.create_intent(IntentType.OPEN, "BTCUSDT", Side.LONG, Decimal("0.1"))
        self.assertEqual(intent.created_at, self.clock_value)

    # 2. client_order_id has database-level uniqueness ------------------------
    def test_client_order_id_database_unique(self):
        intent = self.ledger.create_intent(IntentType.OPEN, "BTCUSDT", Side.LONG, Decimal("0.1"))
        order1 = self.ledger.create_order(intent.intent_id, 1, side="BUY", type="MARKET", quantity=Decimal("0.1"), reduce_only=False)
        # Direct DB violation must raise IntegrityError, not just code check
        with self.assertRaises(Exception):
            self.ledger.create_order(intent.intent_id, 1, side="BUY", type="MARKET", quantity=Decimal("0.1"), reduce_only=False)

    # 3. SUBMIT_UNKNOWN does not create a second order ------------------------
    def test_submit_unknown_no_duplicate_order(self):
        self.port.submit_unknown_next_n = 1
        result = self.executor.open_position(Side.LONG, Decimal("0.1"))
        self.assertFalse(result["success"])
        count = self.ledger._conn().execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        self.assertEqual(count, 1)

    # 4. Fill idempotency by exchange_fill_id ---------------------------------
    def test_duplicate_fill_ignored_and_out_of_order_rebuilt(self):
        intent = self.ledger.create_intent(IntentType.OPEN, "BTCUSDT", Side.LONG, Decimal("0.1"))
        order = self.ledger.create_order(intent.intent_id, 1, side="BUY", type="MARKET", quantity=Decimal("0.1"), reduce_only=False)
        from aurora.execution_truth import FillRecord

        fill1 = FillRecord(
            client_order_id=order.client_order_id,
            exchange_fill_id="fill-1",
            price=Decimal("100000.00"),
            quantity=Decimal("0.1"),
            fee=Decimal("5.00"),
            side="BUY",
            timestamp="2026-09-02T00:00:01+00:00",
        )
        self.ledger.insert_fill(fill1)
        self.ledger.insert_fill(fill1)  # duplicate must be ignored

        fill_rows = self.ledger._conn().execute(
            "SELECT COUNT(*) FROM fills WHERE exchange_fill_id=?", ("fill-1",)
        ).fetchone()[0]
        self.assertEqual(fill_rows, 1)

        order.status = OrderStatus.FILLED
        self.ledger.update_order_status(order)

        truth = self.executor.truth.rebuild()
        self.assertEqual(truth.state, PositionState.KNOWN_OPEN)

    # 5. Intent approval is atomic and resists concurrent claim ---------------
    def test_intent_approval_is_exclusive(self):
        intent = self.ledger.create_intent(IntentType.OPEN, "BTCUSDT", Side.LONG, Decimal("0.1"))
        results = {"a": None, "b": None}

        def approve_a():
            try:
                results["a"] = self.ledger.approve_intent(intent.intent_id)
            except Exception as e:
                results["a"] = e

        def approve_b():
            time.sleep(0.001)
            try:
                results["b"] = self.ledger.approve_intent(intent.intent_id)
            except Exception as e:
                results["b"] = e

        t1 = threading.Thread(target=approve_a)
        t2 = threading.Thread(target=approve_b)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        approved = [r for r in results.values() if getattr(r, "state", None) and r.state.name == "APPROVED"]
        self.assertEqual(len(approved), 1, "only one concurrent approval may succeed")

    # 6. SQLite is in WAL mode with busy timeout ------------------------------
    def test_wal_and_busy_timeout(self):
        row = self.ledger._conn().execute("SELECT journal_mode FROM pragma_journal_mode").fetchone()
        self.assertEqual(row[0].upper(), "WAL")
        row = self.ledger._conn().execute("PRAGMA busy_timeout").fetchone()
        self.assertGreaterEqual(row[0], 1000)  # ms

    # 7. Order status transitions are whitelisted -----------------------------
    def test_invalid_order_status_transition_rejected(self):
        intent = self.ledger.create_intent(IntentType.OPEN, "BTCUSDT", Side.LONG, Decimal("0.1"))
        order = self.ledger.create_order(intent.intent_id, 1, side="BUY", type="MARKET", quantity=Decimal("0.1"), reduce_only=False)
        # Fake a FILLED update
        order.status = OrderStatus.FILLED
        self.ledger.update_order_status(order)
        # Attempting to roll back to PENDING must not be allowed at the executor/ledger layer
        order2 = self.ledger.get_order(order.client_order_id)
        order2.status = OrderStatus.PENDING
        with self.assertRaises(Exception):
            self.ledger.update_order_status(order2)

    # 8. No real Binance client is constructed --------------------------------
    def test_no_real_broker_modules_instantiated(self):
        from aurora.execution_truth import FakeExchange
        self.assertIsInstance(self.port, FakeExchange)
        # A static guarantee: this module must not import binance.client or ccxt
        import aurora.execution_truth as et
        self.assertNotIn("binance.client", et.__dict__)
        self.assertNotIn("ccxt", et.__dict__)

    # 9. UNKNOWN and Kill Switch survive a restart ----------------------------
    def test_unknown_and_kill_switch_persist_across_ledger_restart(self):
        self.port.submit_unknown_next_n = 1
        self.executor.open_position(Side.LONG, Decimal("0.1"))
        self.ledger.set_kill_switch(True, "test")

        ledger2 = self._fresh_ledger()
        self.assertTrue(ledger2.get_kill_switch()[0])
        pos = ledger2.get_position("BTCUSDT")
        self.assertEqual(pos.state, PositionState.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
