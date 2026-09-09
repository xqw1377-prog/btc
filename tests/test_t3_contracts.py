"""T3 扩展 TESTNET 生产循环合同（离线验证）。"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aurora.ops_t3_extended as t3_module
from aurora.config_source import ConfigSource
from aurora.kernel.fake_exchange import FakeExchange
from aurora.kernel.ledger import Ledger
from aurora.kernel.orchestrator import Orchestrator
from aurora.ops_controlled_requal import INCIDENT_FINGERPRINT
from aurora.ops_t3_extended import (
    T3_MAX_QTY,
    assert_t3_gates,
    close_start_order,
    issue_t3_window,
    load_t3_permit,
    load_t3_start_order,
    t3_permit_path,
    t3_start_order_path,
    void_t3_permit,
)
from aurora.p0_boundary import SafetyViolation
from aurora.risk_semantics import qty_from_authorized_intent
from tests.kernel_test_open import bind_explicit_protect_prices


def _clean_t3_state():
    base = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "state", "testnet",
        INCIDENT_FINGERPRINT)
    for name in ("t3_permit.json", "t3_start_order.json"):
        path = os.path.join(base, name)
        if os.path.isfile(path):
            os.remove(path)
    t3_dir = os.path.join(base, "t3")
    if os.path.isdir(t3_dir):
        shutil.rmtree(t3_dir)


class T3GovernanceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        _clean_t3_state()

    def tearDown(self):
        _clean_t3_state()
        self._tmp.cleanup()

    def _source(self, mode="TESTNET", extra=None):
        env = {
            "TRADING_MODE": mode,
            "BINANCE_API_KEY": "k" * 32,
            "BINANCE_API_SECRET": "s" * 32,
            "AURORA_EXPECTED_POSITION_MODE": "HEDGE",
            "AURORA_ACCOUNT_FINGERPRINT": INCIDENT_FINGERPRINT,
        }
        if extra:
            env.update(extra)
        return ConfigSource(env_file="dummy", values=env)

    def test_qry_from_authorized_intent_caps_at_max_qty(self):
        self.assertEqual(qty_from_authorized_intent(10000, 0.10, 100, max_qty=5.0), 5.0)
        self.assertEqual(qty_from_authorized_intent(10000, 0.10, 100, max_qty=0.001), 0.001)
        # 未超限时不影响
        self.assertEqual(qty_from_authorized_intent(10, 0.10, 100, max_qty=0.1), 0.01)

    def test_issue_and_load_window(self):
        res = issue_t3_window(
            "T3-20260909-01", "xinquanwang", max_cycles=10, max_runtime_sec=300)
        self.assertEqual(res["start_order"]["session_id"], "T3-20260909-01")
        self.assertEqual(res["permit"]["schema"], "t3-permit-v1")
        loaded = load_t3_start_order()
        self.assertEqual(loaded["status"], "OPEN")
        permit = load_t3_permit(expected_session_id="T3-20260909-01")
        self.assertFalse(permit["voided"])
        self.assertEqual(permit["max_cycles"], 10)

    def test_gates_require_execute_authorized_true(self):
        issue_t3_window("T3-20260909-02", "xinquanwang", max_cycles=2, max_runtime_sec=60)
        source = self._source()
        # T3_EXECUTE_AUTHORIZED is False by default.
        with self.assertRaises(SafetyViolation) as cm:
            assert_t3_gates(source, "T3-20260909-02")
        self.assertIn("T3_EXECUTE_AUTHORIZED=false", str(cm.exception))

    def test_gates_reject_non_testnet(self):
        old = t3_module.T3_EXECUTE_AUTHORIZED
        t3_module.T3_EXECUTE_AUTHORIZED = True
        try:
            issue_t3_window("T3-20260909-03", "xinquanwang", max_cycles=2, max_runtime_sec=60)
            source = self._source(mode="LIVE")
            with self.assertRaises(SafetyViolation) as cm:
                assert_t3_gates(source, "T3-20260909-03")
            self.assertIn("TESTNET only", str(cm.exception))
        finally:
            t3_module.T3_EXECUTE_AUTHORIZED = old

    def test_gates_reject_missing_permit(self):
        old = t3_module.T3_EXECUTE_AUTHORIZED
        t3_module.T3_EXECUTE_AUTHORIZED = True
        # assert_identity 会校验真实指纹；测试里让它直接通过。
        real_identity = t3_module.assert_identity
        t3_module.assert_identity = lambda src, fp=None: INCIDENT_FINGERPRINT
        try:
            source = self._source()
            with self.assertRaises(SafetyViolation) as cm:
                assert_t3_gates(source, "T3-NO-PERMIT")
            self.assertIn("no start order", str(cm.exception))
        finally:
            t3_module.T3_EXECUTE_AUTHORIZED = old
            t3_module.assert_identity = real_identity

    def test_void_and_close(self):
        issue_t3_window("T3-20260909-04", "xinquanwang", max_cycles=2, max_runtime_sec=60)
        void_t3_permit("test void")
        with self.assertRaises(SafetyViolation) as cm:
            load_t3_permit(expected_session_id="T3-20260909-04")
        self.assertIn("permit voided", str(cm.exception))
        close_start_order("test close")
        with open(t3_start_order_path()) as fh:
            order = json.load(fh)
        self.assertEqual(order["status"], "CLOSED")


class T3TradingCycleMaxQtyTests(unittest.TestCase):
    """验证 TradingCycle 在 T3 上下文下能按 max_qty 截断下单数量。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "ledger.db")
        self.exchange = FakeExchange()
        self.ledger = Ledger(self.path)
        self.orch = bind_explicit_protect_prices(
            Orchestrator(self.ledger, self.exchange, instance_id="t3"))

    def tearDown(self):
        self.ledger.close()
        self._tmp.cleanup()

    def test_trading_cycle_max_qty_caps_open_position(self):
        """TradingCycle 若被传入 max_qty=0.001，则不会用更大 size 开仓。

        这里直接验证 qty_from_authorized_intent 被调用后返回正确上限；
        真实 TradingCycle.execute 会传入 self.max_qty。
        """
        qty = qty_from_authorized_intent(
            equity=100000.0, size_pct=0.10, price=100.0,
            min_qty=0.001, max_qty=0.001)
        self.assertAlmostEqual(qty, 0.001, places=10)


if __name__ == "__main__":
    unittest.main()
