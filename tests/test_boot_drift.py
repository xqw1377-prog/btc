"""G0-1 提交一：BOOT-DRIFT 启动独立发现与恢复门禁。

核心不变量：本地账本没有记录，不等于交易所没有仓位；
仓位级事实必须由账本证据解释，否则阻断新增风险——不认领、不误平。
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.kernel.fake_exchange import FakeExchange  # noqa: E402
from aurora.kernel.ledger import Ledger, PositionFactState  # noqa: E402
from aurora.kernel.orchestrator import Orchestrator  # noqa: E402
from aurora.kernel.port import OrderKind  # noqa: E402
from aurora.kernel.state_machine import IntentState  # noqa: E402


class BootDriftHarness(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "ledger.db")
        self.exchange = FakeExchange()
        self.ledger = Ledger(self.path)
        self.orch = Orchestrator(self.ledger, self.exchange, instance_id="t")

    def tearDown(self):
        self.ledger.close()
        self._tmp.cleanup()

    def _fact(self):
        return self.ledger.get_position_fact("BTCUSDT")


class BootDriftDiscoveryTests(BootDriftHarness):
    def test_empty_ledger_exchange_open_blocks_new_risk(self):
        # 账本完全为空，交易所有外部多头 → 独立查询仍发生，BOOT-DRIFT 阻断。
        self.exchange.seed_external_position(0.1, 100000.0)
        report = self.orch.recover()
        self.assertTrue(report["unresolved"])
        self.assertTrue(
            any(e.get("fact") == "BOOT_DRIFT" for e in report["unresolved"])
        )
        self.assertEqual(self._fact()["state"], PositionFactState.UNKNOWN.value)
        # 不认领：不写为 KNOWN_OPEN；不误平：未提交任何订单。
        self.assertEqual(self.exchange.submit_log, [])
        result = self.orch.open_position("LONG", 0.01)
        self.assertFalse(result["success"])
        self.assertEqual(self.exchange.submit_log, [])

    def test_external_short_also_detected(self):
        self.exchange.seed_external_position(-0.05, 90000.0)
        report = self.orch.recover()
        self.assertTrue(
            any(e.get("fact") == "BOOT_DRIFT" for e in report["unresolved"])
        )
        self.assertEqual(self._fact()["state"], PositionFactState.UNKNOWN.value)

    def test_ambiguous_position_is_unknown_not_flat(self):
        # 多腿/覆盖不足 → 查询不完整 → UNKNOWN，绝不净额抵消成 FLAT。
        self.exchange.seed_external_position(0.1, 100000.0)
        self.exchange.seed_external_position(-0.1, 100000.0)
        self.exchange.set_position_query_ambiguous()
        report = self.orch.recover()
        self.assertEqual(self._fact()["state"], PositionFactState.UNKNOWN.value)
        self.assertTrue(report["unresolved"])
        result = self.orch.open_position("LONG", 0.01)
        self.assertFalse(result["success"])

    def test_position_query_failure_is_unknown(self):
        self.exchange._fail_position = True
        report = self.orch.recover()
        self.assertEqual(self._fact()["state"], PositionFactState.UNKNOWN.value)
        self.assertTrue(report["unresolved"])
        self.assertFalse(self.orch.open_position("LONG", 0.01)["success"])

    def test_flat_with_unresolved_pending_blocks_open(self):
        # 残留一笔未决 ENTRY 提交（订单查询也失败），双方仓位为空：
        # 可以记录 FLAT 观察，但恢复未完成，新增开仓必须被拒。
        self.orch.recover()  # 双空 → KNOWN_FLAT，允许进入提交流程
        self.exchange.entry_behavior = "timeout_then_gone"
        self.orch.open_position("LONG", 0.01)  # 留下 SUBMIT_UNKNOWN 未决订单
        self.assertTrue(self.ledger.pending_orders())

        exchange2 = FakeExchange()
        exchange2._fail_order_query = True  # 恢复查询也失败
        ledger2 = Ledger(self.path)          # 同一账本（进程重启）
        orch2 = Orchestrator(ledger2, exchange2, instance_id="t2")
        report = orch2.recover()
        self.assertTrue(report["unresolved"])
        result = orch2.open_position("LONG", 0.01)
        self.assertFalse(result["success"])
        ledger2.close()

    def test_ledger_open_exchange_flat_without_evidence_is_drift(self):
        # 账本记 KNOWN_OPEN 但交易所确认空仓、且无任何成交/平仓证据：
        # 识别差异，不虚构成交，保持恢复未完成。
        self.ledger.set_position_fact(
            "BTCUSDT", PositionFactState.KNOWN_OPEN,
            qty=0.1, side="LONG", source="test")
        report = self.orch.recover()
        self.assertTrue(
            any(e.get("fact") == "BOOT_DRIFT" for e in report["unresolved"])
        )
        self.assertEqual(self._fact()["state"], PositionFactState.UNKNOWN.value)
        self.assertEqual(self.exchange.submit_log, [])  # 未制造平仓单

    def test_clean_flat_boot_allows_open(self):
        report = self.orch.recover()
        self.assertFalse(report["unresolved"])
        self.assertEqual(self._fact()["state"], PositionFactState.KNOWN_FLAT.value)
        result = self.orch.open_position("LONG", 0.01, stop_price=99000.0)
        self.assertTrue(result.get("success") or result.get("intent_id"))
        self.assertTrue(
            any(r.order_kind == OrderKind.ENTRY for r in self.exchange.submit_log)
        )

    def test_recover_idempotent_unknown_fact_is_not_ownership(self):
        # 不变量：UNKNOWN fact ≠ ownership evidence。
        # 第一次 recover 已写入 UNKNOWN 行；第二次不得因"账本有记录"就认领。
        self.exchange.seed_external_position(0.1, 100000.0)
        r1 = self.orch.recover()
        self.assertEqual(self._fact()["state"], PositionFactState.UNKNOWN.value)
        r2 = self.orch.recover()
        self.assertTrue(r1["unresolved"] and r2["unresolved"])
        self.assertEqual(self._fact()["state"], PositionFactState.UNKNOWN.value)
        self.assertEqual(self.exchange.submit_log, [])
        # 持久化安全状态不被重复启动清除
        self.ledger.engage_kill("test kill")
        r3 = self.orch.recover()
        self.assertTrue(r3["kill_engaged"])
        self.assertTrue(r3["unresolved"])


class RecoveryConvergenceSourceTests(BootDriftHarness):
    def test_sl_fill_converges_by_ledger_state_not_report_field(self):
        """不变量：恢复收敛由持久化事实/终态证明，report 只是观察输出。

        交易所侧 SL 触发走 _reconcile_protected_intents，成交入账但不进
        report["resolved"]；审计器不得因此把已收敛状态误判成 BOOT-DRIFT。
        """
        self.orch.recover()
        self.orch.open_position("LONG", 0.01, intent_id="CONV")
        self.exchange.fire_protection("CONV-SL", price=99.0)
        self.ledger.close()
        self.ledger = Ledger(self.path)
        orch2 = Orchestrator(self.ledger, self.exchange, instance_id="t2")
        report = orch2.recover()
        self.assertEqual(report["unresolved"], [])
        self.assertEqual(report["resolved"], [])  # 报告字段确实为空
        self.assertEqual(
            self.ledger.get_intent("CONV")["state"], IntentState.RECONCILED.value)
        self.assertEqual(len(self.ledger.fills_for_order("CONV-SL")), 1)
        self.assertEqual(self._fact()["state"], PositionFactState.KNOWN_FLAT.value)

    def test_matched_ledger_and_exchange_recovers_explainably(self):
        self.orch.recover()
        self.orch.open_position("LONG", 0.01, intent_id="MATCH")
        self.ledger.close()
        self.ledger = Ledger(self.path)
        orch2 = Orchestrator(self.ledger, self.exchange, instance_id="t2")
        report = orch2.recover()
        self.assertEqual(report["unresolved"], [])
        self.assertEqual(self._fact()["state"], PositionFactState.KNOWN_OPEN.value)
        self.assertEqual(self.exchange.submit_log[-1].client_order_id[-3:], "-TP")


class ProductionChainGateTests(unittest.TestCase):
    def test_trading_cycle_holds_while_recovery_unresolved(self):
        """恢复未完成时，大脑不得管理仓位，也不得继续 OPEN/CLOSE。"""
        from aurora.trading_cycle import TradingCycle
        from aurora.p0_boundary import RunMode

        class FakeRuntime:
            def __init__(self):
                self.open_calls = 0
                self.exchange = FakeExchange()

            def recover(self):
                return {
                    "resolved": [], "kill_engaged": False,
                    "unresolved": [{"fact": "BOOT_DRIFT"}],
                }

            class ledger:  # noqa: D106 - duck-typed kill_state
                @staticmethod
                def kill_state():
                    return {"engaged": False}

            def open_position(self, *a, **k):
                self.open_calls += 1
                return {"success": True}

            def close_position(self, *a, **k):
                self.open_calls += 1
                return {"success": True}

        runtime = FakeRuntime()
        cycle = TradingCycle(
            runtime=runtime, client=None, mode=RunMode.TESTNET, capital=1000.0,
        )
        result = cycle.step(enable=True)
        self.assertEqual(result["action"], "HOLD")
        self.assertEqual(runtime.open_calls, 0)


if __name__ == "__main__":
    unittest.main()
