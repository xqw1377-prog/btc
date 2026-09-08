"""CONTROLLED TESTNET REQUAL 离线验收：计划门禁 + FakeExchange 单次会话。"""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.kernel.fake_exchange import FakeExchange  # noqa: E402
from aurora.kernel.ledger import Ledger  # noqa: E402
from aurora.kernel.orchestrator import Orchestrator  # noqa: E402
from aurora.ops_controlled_requal import (  # noqa: E402
    FORBIDDEN_INTENT_MARK,
    INCIDENT_INTENT,
    MAX_NOTIONAL_USDT,
    MAX_QTY,
    assert_intent_allowed,
    assert_scale,
    EXECUTE_AUTHORIZED,
    assert_session_ledger_isolated,
    assert_session_start,
    assert_stop_price,
    execute_live,
    incident_ledger_path,
    main,
    plan,
    run_session,
    session_ledger_path,
)
from aurora.p0_boundary import SafetyViolation  # noqa: E402


def _incident_db(path):
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE kill_switch (id INTEGER PRIMARY KEY, engaged INTEGER, reason TEXT)"
    )
    conn.execute("INSERT INTO kill_switch VALUES (1, 1, 'incident')")
    conn.commit()
    conn.close()


class PlanGateTests(unittest.TestCase):
    def test_plan_defaults_are_frozen_limits(self):
        report = plan(qty=MAX_QTY)
        self.assertEqual(report["execute"], "DENIED")
        self.assertEqual(report["qty"], 0.001)
        self.assertEqual(report["side"], "LONG")
        self.assertEqual(report["productionMain"], "DENIED")
        self.assertTrue(report["sessionLedger"].endswith("controlled_requal.db"))
        self.assertNotEqual(report["sessionLedger"], report["incidentLedger"])

    def test_qty_and_notional_caps(self):
        with self.assertRaises(SafetyViolation):
            assert_scale(0.002, 100.0)
        with self.assertRaises(SafetyViolation):
            assert_scale(MAX_QTY, (MAX_NOTIONAL_USDT / MAX_QTY) + 1)
        assert_scale(MAX_QTY, 100.0)

    def test_incident_intent_forbidden(self):
        with self.assertRaises(SafetyViolation):
            assert_intent_allowed(INCIDENT_INTENT)
        with self.assertRaises(SafetyViolation):
            assert_intent_allowed(f"AURORA-{FORBIDDEN_INTENT_MARK}-X")

    def test_session_path_cannot_be_incident(self):
        with self.assertRaises(SafetyViolation):
            assert_session_ledger_isolated(incident_ledger_path())
        assert_session_ledger_isolated(session_ledger_path())

    def test_source_has_no_production_main(self):
        src = open(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "aurora", "ops_controlled_requal.py")).read()
        self.assertNotIn("import aurora.production_main", src)
        self.assertNotIn("from aurora.production_main", src)
        self.assertNotIn("from aurora.trading_cycle", src)
        self.assertNotIn("ensure_ledger_migrated", src)

    def test_main_execute_flag_still_denied(self):
        code = main(["--i-execute-controlled-requal", "--qty", "0.001"])
        self.assertEqual(code, 3)

    def test_main_plan_only_zero(self):
        self.assertEqual(main([]), 0)

    def test_execute_live_hard_denied(self):
        self.assertFalse(EXECUTE_AUTHORIZED)
        with self.assertRaises(SafetyViolation):
            execute_live()

    def test_long_stop_must_be_below_mark(self):
        with self.assertRaises(SafetyViolation):
            assert_stop_price(100.0, 100.0)
        assert_stop_price(99.0, 100.0)


class OfflineSessionTests(unittest.TestCase):
    def test_one_shot_protect_restart_flatten_kills_session_not_incident(self):
        with tempfile.TemporaryDirectory() as tmp:
            incident = os.path.join(tmp, "kernel_ledger.db")
            session = os.path.join(tmp, "controlled_requal.db")
            _incident_db(incident)
            before = open(incident, "rb").read()
            exchange = FakeExchange(price=100.0)
            ledger = Ledger(session)
            orch = Orchestrator(ledger, exchange, instance_id="ctr")
            orch.recover()
            out = run_session(
                orch, qty=0.001, mark_price=100.0, stop_price=99.0,
                intent_id="AURORA-CTR-test001", incident_path=incident)
            try:
                self.assertTrue(out["success"], out)
                self.assertEqual(out["opened"]["state"], "PROTECTED")
                self.assertAlmostEqual(out["opened"]["protected_qty"], 0.001, places=10)
                self.assertEqual(out["restartRecover"], "PASS")
                self.assertEqual(out["sessionKill"]["engaged"], 1)
                self.assertEqual(open(incident, "rb").read(), before)
                self.assertEqual(exchange.position("BTCUSDT").signed_qty, 0.0)
            finally:
                ledger.close()

    def test_oversize_refused_before_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "controlled_requal.db")
            ledger = Ledger(path)
            orch = Orchestrator(ledger, FakeExchange(), instance_id="ctr")
            orch.recover()
            try:
                with self.assertRaises(SafetyViolation):
                    run_session(
                        orch, qty=0.007, mark_price=100.0, stop_price=99.0)
            finally:
                ledger.close()

    def test_start_not_flat_refuses_and_kills_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "controlled_requal.db")
            exchange = FakeExchange(price=100.0)
            ledger = Ledger(path)
            orch = Orchestrator(ledger, exchange, instance_id="ctr")
            orch.recover()
            exchange.seed_external_position(0.002, 100.0)
            try:
                with self.assertRaises(SafetyViolation):
                    run_session(
                        orch, qty=0.001, mark_price=100.0, stop_price=99.0)
                self.assertEqual(ledger.kill_state()["engaged"], 1)
            finally:
                ledger.close()

    def test_unknown_position_refuses_start(self):
        exchange = FakeExchange()
        exchange.set_position_query_ambiguous(True)
        with self.assertRaises(SafetyViolation):
            assert_session_start(exchange)

    def test_protection_reject_kills_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "controlled_requal.db")
            exchange = FakeExchange(price=100.0, protection_behavior="reject")
            ledger = Ledger(path)
            orch = Orchestrator(ledger, exchange, instance_id="ctr")
            orch.recover()
            try:
                out = run_session(
                    orch, qty=0.001, mark_price=100.0, stop_price=99.0,
                    intent_id="AURORA-CTR-slfail")
                self.assertFalse(out["success"])
                self.assertIn(out["phase"], ("OPEN", "SL"))
                self.assertEqual(ledger.kill_state()["engaged"], 1)
            finally:
                ledger.close()


if __name__ == "__main__":
    unittest.main()
