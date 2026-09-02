"""P0-C 安全验收门禁矩阵（离线部分）。

对应用户指定的 10 个必须自动化验证的场景。每个测试即一条门禁，
全部离线：FakeExchange + 临时 SQLite + environ 注入，零网络。

WS 断线补齐（G9）在 P0-B1 阶段以离线等价物验证：
"提交结果未知 → 重启 → 按 client_order_id 查询事实补齐成交"。
真实 WS 属 P0-B2，届时在此矩阵追加在线版本。
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
from aurora.p0_boundary import (  # noqa: E402
    BrainPosition,
    Persistence,
    PositionQueryKind,
    PositionSnapshot,
    ReconcileStatus,
    RunMode,
    SafetyStore,
    SafetyViolation,
    assert_endpoint,
    boot,
    key_fingerprint,
    reconcile,
    resolve_mode,
)
try:
    from test_p0_safety import FakeBroker  # noqa: E402
except ImportError:  # tests/ 存在 __init__.py 时按包导入
    from tests.test_p0_safety import FakeBroker  # noqa: E402


class KernelHarness(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "ledger.db")
        self.exchange = FakeExchange()
        self.ledger = Ledger(self.path)
        self.orch = Orchestrator(self.ledger, self.exchange, instance_id="gate")
        report = self.orch.recover()
        self.assertFalse(report["kill_engaged"])

    def tearDown(self):
        self.ledger.close()
        self._tmp.cleanup()


class G1ModesNeverCross(unittest.TestCase):
    """PAPER、TESTNET、LIVE 不会串环境。"""

    def test_paper_never_attaches_exchange(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SafetyViolation):
                boot(os.path.join(tmp, "p.json"), os.path.join(tmp, "lk"),
                     broker=FakeBroker(), environ={"TRADING_MODE": "PAPER"})

    def test_testnet_never_mainnet_endpoint(self):
        with self.assertRaises(SafetyViolation):
            assert_endpoint("https://fapi.binance.com", RunMode.TESTNET)

    def test_live_requires_dual_auth_even_then_no_go(self):
        key = "k"
        fp = key_fingerprint(key)
        env = {
            "TRADING_MODE": "LIVE",
            "ALLOW_LIVE_TRADING": "true",
            "AURORA_LIVE_CONFIRM": "I_UNDERSTAND_LIVE_RISK",
            "BINANCE_API_KEY": key,
            "AURORA_ACCOUNT_FINGERPRINT": fp,
            "AURORA_LIVE_KEY_SHA256": fp,
        }
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SafetyViolation) as ctx:
                boot(os.path.join(tmp, "p.json"), os.path.join(tmp, "lk"),
                     broker=FakeBroker(url="https://fapi.binance.com"), environ=env)
            self.assertIn("NO-GO", str(ctx.exception))

    def test_unknown_mode_refuses(self):
        with self.assertRaises(SafetyViolation):
            resolve_mode({"TRADING_MODE": "PRODUCTION"})


class G2PositionQueryFailureIsNotFlat(KernelHarness):
    """查询持仓失败绝不被解释为空仓。"""

    def test_unknown_snapshot_and_blocked_open(self):
        self.exchange.fail_position_queries(True)
        self.orch.recover()  # 交易所事实不可知 → UNKNOWN，不是 FLAT
        fact = self.ledger.get_position_fact("BTCUSDT")
        self.assertEqual(fact["state"], PositionFactState.UNKNOWN.value)
        result = self.orch.open_position("LONG", 0.01, intent_id="G2")
        self.assertFalse(result["success"])
        entries = [r for r in self.exchange.submit_log if r.order_kind == OrderKind.ENTRY]
        self.assertEqual(len(entries), 0)


class G3FailedCloseNeverReverseOpens(KernelHarness):
    """平仓失败绝不反向开仓。"""

    def test_close_unknown_blocks_new_opens(self):
        self.orch.open_position("LONG", 0.01, intent_id="G3")
        self.exchange.close_behavior = "timeout_then_gone"
        closed = self.orch.close_position("signal exit")
        self.assertFalse(closed["success"])
        self.assertEqual(closed["state"], "RECOVERY_REQUIRED")
        # kill 已熔断 → 一切新开（含反向）被拒
        reverse = self.orch.open_position("SHORT", 0.01, intent_id="G3r")
        self.assertFalse(reverse["success"])
        self.assertIn("kill switch", reverse["reason"])


class G4SlFailureFlattensAndKills(KernelHarness):
    """SL 挂单失败会自动减仓并熔断。"""

    def test_protection_reject_directional_flatten(self):
        self.exchange.protection_behavior = "reject"
        result = self.orch.open_position("LONG", 0.01, intent_id="G4")
        self.assertFalse(result["success"])
        self.assertTrue(result.get("halt"))
        closes = [r for r in self.exchange.submit_log
                  if r.order_kind == OrderKind.CLOSE and r.reduce_only]
        self.assertEqual(len(closes), 1)
        self.assertEqual(self.exchange.position("BTCUSDT").signed_qty, 0.0)
        self.assertTrue(self.ledger.kill_state()["engaged"])


class G5RestartKeepsRiskState(unittest.TestCase):
    """进程重启不会清除日亏、回撤和 Kill Switch。"""

    def test_p0_store_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "p0.json")
            Persistence(path).save(SafetyStore(
                kill_switch=True, kill_reason="daily loss",
                daily_pnl=-88.0, drawdown=0.07,
                pending_orders=[{"id": "SL1", "type": "SL"}]))
            with self.assertRaises(SafetyViolation):
                # 重启路径：restore_or_refuse 对持久化 kill 拒绝启动
                from aurora.p0_boundary import restore_or_refuse
                restore_or_refuse(Persistence(path))
            loaded = Persistence(path).load()
            self.assertTrue(loaded.kill_switch)
            self.assertEqual(loaded.daily_pnl, -88.0)

    def test_kernel_kill_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "l.db")
            ledger = Ledger(path)
            ledger.engage_kill("drawdown breach")
            ledger.close()
            reopened = Ledger(path)
            exchange = FakeExchange()
            orch = Orchestrator(reopened, exchange, instance_id="r")
            result = orch.open_position("LONG", 0.01, intent_id="G5")
            self.assertFalse(result["success"])
            self.assertIn("kill switch", result["reason"])
            reopened.close()


class G6ExchangeSideSlFillsEnterLedger(KernelHarness):
    """交易所侧 SL/TP 成交能进入账本（学习样本接入属后续阶段）。"""

    def test_sl_fire_reconciled_with_fills(self):
        self.orch.open_position("LONG", 0.01, intent_id="G6")
        self.exchange.fire_protection("G6-SL", price=98.0)
        self.ledger.close()
        self.ledger = Ledger(self.path)
        self.orch = Orchestrator(self.ledger, self.exchange, instance_id="gate2")
        report = self.orch.recover()
        self.assertEqual(len(report["unresolved"]), 0)
        self.assertEqual(
            self.ledger.get_intent("G6")["state"], IntentState.RECONCILED.value)
        fills = self.ledger.fills_for_order("G6-SL")
        self.assertEqual(len(fills), 1)


class G7DuplicateEventsNoDuplicateOrders(KernelHarness):
    """重复事件不会造成重复下单。"""

    def test_intent_replay_and_duplicate_fill_idempotent(self):
        first = self.orch.open_position("LONG", 0.01, intent_id="G7")
        self.assertTrue(first["success"])
        replay = self.orch.open_position("LONG", 0.01, intent_id="G7")
        self.assertFalse(replay["success"])
        self.assertTrue(replay["replay"])
        entries = [r for r in self.exchange.submit_log if r.order_kind == OrderKind.ENTRY]
        self.assertEqual(len(entries), 1)
        fill = self.exchange.fills("G7-ENTRY")[0]
        self.assertFalse(self.ledger.insert_fill(
            fill.fill_id, fill.client_order_id, fill.qty, fill.price,
            fill.fee, fill.side, fill.filled_at))
        self.assertEqual(len(self.ledger.fills_for_order("G7-ENTRY")), 1)


class G8PartialFillProtectedAndReconciled(KernelHarness):
    """部分成交能够正确补保护和对账。"""

    def test_partial_fill_protection_qty_matches(self):
        self.exchange.entry_behavior = "partial"
        result = self.orch.open_position("LONG", 0.010, intent_id="G8")
        self.assertEqual(result["state"], "PROTECTED")
        self.assertAlmostEqual(result["protected_qty"], 0.006, places=10)
        fact = self.ledger.get_position_fact("BTCUSDT")
        self.assertAlmostEqual(fact["qty"], 0.006, places=10)
        self.assertEqual(fact["state"], PositionFactState.KNOWN_OPEN.value)


class G9UnknownResolvedByFactQuery(KernelHarness):
    """断线/超时期间的成交可通过事实查询补齐（离线等价：SUBMIT_UNKNOWN→query）。"""

    def test_timeout_then_filled_no_second_order(self):
        self.exchange.entry_behavior = "timeout_then_filled"
        result = self.orch.open_position("LONG", 0.01, intent_id="G9")
        self.assertEqual(result["state"], "SUBMIT_UNKNOWN")
        self.ledger.close()
        self.ledger = Ledger(self.path)
        self.orch = Orchestrator(self.ledger, self.exchange, instance_id="gate2")
        self.orch.recover()
        self.assertEqual(
            self.ledger.get_intent("G9")["state"], IntentState.PROTECTED.value)
        entries = [r for r in self.exchange.submit_log if r.order_kind == OrderKind.ENTRY]
        self.assertEqual(len(entries), 1)
        self.assertEqual(len(self.ledger.fills_for_order("G9-ENTRY")), 1)


class G10GhostAndUnknownEnterRecovery(KernelHarness):
    """幽灵仓位和交易所未知仓位都能进入恢复流程。"""

    def test_ledger_open_exchange_flat_ghost_reconciled(self):
        self.orch.open_position("LONG", 0.01, intent_id="G10")
        # 交易所已被外部平仓（如手动平仓），账本仍 PROTECTED = 幽灵仓位
        self.exchange.fire_protection("G10-TP", price=101.0)
        self.orch.recover()
        self.assertEqual(
            self.ledger.get_intent("G10")["state"], IntentState.RECONCILED.value)
        self.assertEqual(
            self.ledger.get_position_fact("BTCUSDT")["state"],
            PositionFactState.KNOWN_FLAT.value)

    def test_p0_ghost_brain_cleared_by_reconcile(self):
        store = SafetyStore(brain=BrainPosition(True, "LONG", 0.01, 100.0))
        rec = reconcile(store, PositionSnapshot(kind=PositionQueryKind.FLAT), "boot")
        self.assertEqual(rec.status, ReconcileStatus.MATCHED)
        self.assertFalse(store.brain.is_open)

    def test_exchange_open_brain_flat_is_drift_not_auto_open(self):
        store = SafetyStore()
        rec = reconcile(
            store,
            PositionSnapshot(kind=PositionQueryKind.OPEN, side="LONG", size=0.01),
            "boot",
        )
        self.assertEqual(rec.status, ReconcileStatus.DRIFT_DETECTED)


if __name__ == "__main__":
    unittest.main()
