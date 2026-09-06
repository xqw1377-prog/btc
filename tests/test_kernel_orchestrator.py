"""P0-B1 编排器故障注入验收测试（对应 12 项门禁场景，全部离线）。"""
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


class Harness(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "ledger.db")
        self.exchange = FakeExchange()
        self.ledger = Ledger(self.path)
        self.orch = Orchestrator(self.ledger, self.exchange, instance_id="orch-A")

    def tearDown(self):
        self.ledger.close()
        self._tmp.cleanup()

    def _boot_flat(self):
        report = self.orch.recover()
        self.assertFalse(report["kill_engaged"])
        self.assertEqual(
            self.ledger.get_position_fact("BTCUSDT")["state"],
            PositionFactState.KNOWN_FLAT.value,
        )

    def entry_orders(self):
        return [r for r in self.exchange.submit_log if r.order_kind == OrderKind.ENTRY]


class AcceptanceTests(Harness):
    def test_g1_intent_replay_no_duplicate_order(self):
        self._boot_flat()
        first = self.orch.open_position("LONG", 0.01, intent_id="A1")
        self.assertTrue(first["success"])
        replay = self.orch.open_position("LONG", 0.01, intent_id="A1")
        self.assertFalse(replay["success"])
        self.assertTrue(replay["replay"])
        self.assertEqual(len(self.entry_orders()), 1)

    def test_g2_submit_timeout_then_filled_no_second_order(self):
        self.exchange.entry_behavior = "timeout_then_filled"
        self._boot_flat()
        result = self.orch.open_position("LONG", 0.01, intent_id="A2")
        self.assertEqual(result["state"], "SUBMIT_UNKNOWN")
        self.assertEqual(len(self.entry_orders()), 1)

        # 崩溃重启：新实例恢复，按 client_order_id 查事实，不补第二单
        self.ledger.close()
        self.ledger = Ledger(self.path)
        self.orch = Orchestrator(self.ledger, self.exchange, instance_id="orch-B")
        report = self.orch.recover()
        intent = self.ledger.get_intent("A2")
        self.assertEqual(intent["state"], IntentState.PROTECTED.value)
        self.assertEqual(len(self.entry_orders()), 1)
        self.assertEqual(len(report["unresolved"]), 0)

    def test_g3_partial_fill_protection_matches_actual_qty(self):
        self.exchange.entry_behavior = "partial"
        self._boot_flat()
        result = self.orch.open_position("LONG", 0.010, intent_id="A3")
        # FakeExchange 部分成交 60% → 按实际 0.006 建保护，而非请求量 0.010
        self.assertEqual(result["state"], "PROTECTED")
        self.assertAlmostEqual(result["protected_qty"], 0.006, places=10)
        sl = self.ledger.get_order("A3-SL")
        self.assertAlmostEqual(sl["quantity"], 0.006, places=10)
        self.assertEqual(sl["state"], "ACTIVE")
        self.assertAlmostEqual(
            self.ledger.get_position_fact("BTCUSDT")["qty"], 0.006, places=10)

    def test_g4_protection_failure_triggers_directional_flatten(self):
        self.exchange.protection_behavior = "reject"
        self._boot_flat()
        result = self.orch.open_position("LONG", 0.01, intent_id="A4")
        self.assertFalse(result["success"])
        self.assertTrue(result.get("halt"))
        # 定向 reduceOnly 平仓单确实发出且成交
        closes = [r for r in self.exchange.submit_log
                  if r.order_kind == OrderKind.CLOSE and r.reduce_only]
        self.assertEqual(len(closes), 1)
        # 仓位归零 + 熔断
        self.assertEqual(self.exchange.position("BTCUSDT").signed_qty, 0.0)
        self.assertTrue(self.ledger.kill_state()["engaged"])
        # 熔断后禁止一切新开仓
        after = self.orch.open_position("LONG", 0.01, intent_id="A4b")
        self.assertFalse(after["success"])
        self.assertIn("kill switch", after["reason"])

    def test_g5_close_unknown_goes_recovery_required(self):
        self._boot_flat()
        self.orch.open_position("LONG", 0.01, intent_id="A5")
        self.exchange.close_behavior = "timeout_then_gone"
        result = self.orch.close_position("signal exit")
        self.assertFalse(result["success"])
        self.assertEqual(result["state"], "RECOVERY_REQUIRED")
        self.assertTrue(self.ledger.kill_state()["engaged"])
        fact = self.ledger.get_position_fact("BTCUSDT")
        self.assertEqual(fact["state"], PositionFactState.UNKNOWN.value)

    def test_g6_unknown_position_forbids_new_open(self):
        self._boot_flat()
        self.ledger.set_position_fact(
            "BTCUSDT", PositionFactState.UNKNOWN, source="test", note="query failed")
        result = self.orch.open_position("LONG", 0.01, intent_id="A6")
        self.assertFalse(result["success"])
        self.assertIn("UNKNOWN", result["reason"])
        self.assertEqual(len(self.entry_orders()), 0)

    def test_g6b_exchange_sl_fires_and_enters_ledger_on_restart(self):
        """交易所侧 SL 触发：重启后对账收敛，SL 成交进入账本（幽灵仓位反向）。"""
        self._boot_flat()
        self.orch.open_position("LONG", 0.01, intent_id="A6b")
        # 交易所侧触发 SL（进程此刻"不知情"，模拟崩溃/断连）
        self.exchange.fire_protection("A6b-SL", price=99.0)
        self.ledger.close()
        self.ledger = Ledger(self.path)
        self.orch = Orchestrator(self.ledger, self.exchange, instance_id="orch-B")
        report = self.orch.recover()
        self.assertEqual(len(report["unresolved"]), 0)
        intent = self.ledger.get_intent("A6b")
        self.assertEqual(intent["state"], IntentState.RECONCILED.value)
        sl_fills = self.ledger.fills_for_order("A6b-SL")
        self.assertEqual(len(sl_fills), 1)
        self.assertAlmostEqual(sl_fills[0]["qty"], 0.01, places=10)
        sl_order = self.ledger.get_order("A6b-SL")
        self.assertEqual(sl_order["state"], "FILLED")
        self.assertEqual(
            self.ledger.get_position_fact("BTCUSDT")["state"],
            PositionFactState.KNOWN_FLAT.value)
        # 收敛后可重新开仓
        again = self.orch.open_position("LONG", 0.01, intent_id="A6b-2")
        self.assertTrue(again["success"])

    def test_g6c2_oco_cancel_unknown_not_reconciled(self):
        """全平后兄弟腿撤单未知：熔断且不得标成 RECONCILED。"""
        self._boot_flat()
        self.orch.open_position("LONG", 0.01, intent_id="A6c2")
        self.exchange.fire_protection("A6c2-SL", price=99.0)
        self.exchange.cancel_behavior = "unknown"
        self.orch.recover()
        intent = self.ledger.get_intent("A6c2")
        self.assertEqual(intent["state"], IntentState.RECOVERY_REQUIRED.value)
        self.assertTrue(self.ledger.kill_state()["engaged"])
        self.assertNotEqual(intent["state"], IntentState.RECONCILED.value)

    def test_g13_protection_submit_unknown_not_rejected_or_flattened(self):
        """保护腿提交超时：订单标 SUBMIT_UNKNOWN，禁止当成拒单去紧急平仓。"""
        self.exchange.protection_behavior = "timeout_then_gone"
        self._boot_flat()
        result = self.orch.open_position("LONG", 0.01, intent_id="A13")
        self.assertFalse(result["success"])
        self.assertEqual(result["state"], "RECOVERY_REQUIRED")
        sl = self.ledger.get_order("A13-SL")
        self.assertEqual(sl["state"], "SUBMIT_UNKNOWN")
        closes = [r for r in self.exchange.submit_log
                  if r.order_kind == OrderKind.CLOSE]
        self.assertEqual(closes, [])
        self.assertTrue(self.ledger.kill_state()["engaged"])
        self.assertAlmostEqual(self.exchange.position("BTCUSDT").signed_qty, 0.01)

    def test_g14_recover_survives_order_query_failure(self):
        """恢复路径查询失败必须落 UNKNOWN，不得把进程打崩。"""
        self._boot_flat()
        self.orch.open_position("LONG", 0.01, intent_id="A14")
        self.exchange.fail_order_queries(True)
        report = self.orch.recover()
        self.assertTrue(len(report["unresolved"]) >= 1)
        fact = self.ledger.get_position_fact("BTCUSDT")
        self.assertEqual(fact["state"], PositionFactState.UNKNOWN.value)

    def test_g6c_oco_sibling_leg_cancelled_after_sl_fires(self):
        """OCO 语义：SL 触发后，TP 兄弟腿必须按精确 ID 撤销，不留孤儿挂单。"""
        self._boot_flat()
        self.orch.open_position("LONG", 0.01, intent_id="A6c")
        self.exchange.fire_protection("A6c-SL", price=99.0)
        self.orch.recover()
        tp = self.ledger.get_order("A6c-TP")
        self.assertEqual(tp["state"], "CANCELLED")
        sl = self.ledger.get_order("A6c-SL")
        self.assertEqual(sl["state"], "FILLED")
        self.assertEqual(
            self.ledger.get_intent("A6c")["state"], IntentState.RECONCILED.value)

    def test_g6d_ouo_protection_topup_after_entry_completes(self):
        """OUO 语义：部分成交建保护后入场单补满，保护量必须跟随补足。"""
        self.exchange.entry_behavior = "partial"
        self._boot_flat()
        result = self.orch.open_position("LONG", 0.010, intent_id="A6d")
        self.assertAlmostEqual(result["protected_qty"], 0.006, places=10)
        # 入场单后续成交至全量（模拟迟到/增量 Fill）
        self.exchange.complete_fill("A6d-ENTRY")
        report = self.orch.recover()
        sl_topup = self.ledger.get_order("A6d-SL-TOPUP")
        tp_topup = self.ledger.get_order("A6d-TP-TOPUP")
        self.assertAlmostEqual(sl_topup["quantity"], 0.004, places=10)
        self.assertAlmostEqual(tp_topup["quantity"], 0.004, places=10)
        # 覆盖量按侧计算：SL 侧与 TP 侧各自覆盖全部持仓 0.010
        sides = {"STOP_LOSS": 0.0, "TAKE_PROFIT": 0.0}
        for o in self.ledger.orders_for_intent("A6d"):
            if o["order_kind"] in sides and o["state"] in ("ACTIVE", "FILLED"):
                sides[o["order_kind"]] += o["quantity"]
        self.assertAlmostEqual(sides["STOP_LOSS"], 0.010, places=10)
        self.assertAlmostEqual(sides["TAKE_PROFIT"], 0.010, places=10)
        fact = self.ledger.get_position_fact("BTCUSDT")
        self.assertAlmostEqual(fact["qty"], 0.010, places=10)

    def test_g6e_late_fill_after_reconciled_no_silent_accounting(self):
        """迟到成交（Hummingbot 语义）：只入审计账，不改已对账的持仓事实。"""
        self._boot_flat()
        self.orch.open_position("LONG", 0.01, intent_id="A6e")
        self.exchange.fire_protection("A6e-SL", price=99.0)
        self.orch.recover()
        self.assertEqual(
            self.ledger.get_intent("A6e")["state"], IntentState.RECONCILED.value)
        entry = self.ledger.get_order("A6e-ENTRY")
        recorded = self.ledger.insert_fill(
            "LATE-EVENT-1", "A6e-ENTRY", 0.01, 100.5, 0.0, "BUY", "t-late")
        self.assertTrue(recorded)  # 审计层保留迟到事件
        after = self.ledger.get_order("A6e-ENTRY")
        self.assertAlmostEqual(after["filled_qty"], entry["filled_qty"], places=10)
        self.assertEqual(
            self.ledger.get_intent("A6e")["state"], IntentState.RECONCILED.value)
        self.assertEqual(
            self.ledger.get_position_fact("BTCUSDT")["state"],
            PositionFactState.KNOWN_FLAT.value)

    def test_g7_kill_switch_survives_restart(self):
        self._boot_flat()
        self.ledger.engage_kill("drawdown breach")
        self.ledger.close()
        self.ledger = Ledger(self.path)
        self.orch = Orchestrator(self.ledger, self.exchange, instance_id="orch-B")
        result = self.orch.open_position("LONG", 0.01, intent_id="A7")
        self.assertFalse(result["success"])
        self.assertIn("kill switch", result["reason"])

    def test_g8_pending_order_recovered_on_startup(self):
        self.exchange.entry_behavior = "timeout_then_gone"
        self._boot_flat()
        result = self.orch.open_position("LONG", 0.01, intent_id="A8")
        self.assertEqual(result["state"], "SUBMIT_UNKNOWN")
        self.ledger.close()
        self.ledger = Ledger(self.path)
        self.orch = Orchestrator(self.ledger, self.exchange, instance_id="orch-B")
        report = self.orch.recover()
        intent = self.ledger.get_intent("A8")
        self.assertEqual(intent["state"], IntentState.REJECTED.value)
        # 订单从未存在 → 事实为 NOT_FOUND → 拒绝语义，且恢复后可重新开仓
        self.exchange.entry_behavior = "ok"
        again = self.orch.open_position("LONG", 0.01, intent_id="A8b")
        self.assertTrue(again["success"])

    def test_g9_duplicate_fill_events_single_accounting(self):
        self._boot_flat()
        self.orch.open_position("LONG", 0.01, intent_id="A9")
        fill = self.exchange.fills("A9-ENTRY")[0]
        first = self.ledger.insert_fill(
            fill.fill_id, fill.client_order_id, fill.qty, fill.price,
            fill.fee, fill.side, fill.filled_at)
        second = self.ledger.insert_fill(
            fill.fill_id, fill.client_order_id, fill.qty, fill.price,
            fill.fee, fill.side, fill.filled_at)
        self.assertFalse(first)
        self.assertFalse(second)
        self.assertEqual(len(self.ledger.fills_for_order("A9-ENTRY")), 1)

    def test_g10_ledger_write_failure_never_submits(self):
        self._boot_flat()

        class BrokenLedger:
            def __init__(self, inner):
                self._inner = inner
                self.submitted_calls = 0

            def __getattr__(self, name):
                return getattr(self._inner, name)

            def record_order_submitting(self, *a, **k):
                self.submitted_calls += 1
                raise RuntimeError("disk full")

        broken = BrokenLedger(self.ledger)
        orch = Orchestrator(broken, self.exchange, instance_id="orch-X")
        result = orch.open_position("LONG", 0.01, intent_id="A10")
        self.assertFalse(result["success"])
        self.assertIn("no order sent", result["reason"])
        self.assertEqual(broken.submitted_calls, 1)
        self.assertEqual(len(self.entry_orders()), 0)

    def test_g11_two_executors_cannot_consume_same_intent(self):
        self._boot_flat()
        self.ledger.create_intent("A11", "BTCUSDT", "LONG", 0.01)
        self.assertTrue(self.ledger.claim_intent("A11", "orchestrator-A"))
        self.assertFalse(self.ledger.claim_intent("A11", "orchestrator-B"))
        # 被 A 认领后，B 的 open_position 走拒绝路径且不发单
        result = self.orch.open_position("LONG", 0.01, intent_id="A11")
        self.assertFalse(result["success"])
        self.assertIn("another executor", result["reason"])
        self.assertEqual(len(self.entry_orders()), 0)

    def test_g12_every_transition_has_time_reason_correlation(self):
        self._boot_flat()
        self.exchange.protection_behavior = "reject"
        self.orch.open_position("LONG", 0.01, intent_id="A12")
        rows = [r for r in self.ledger.all_transitions() if r["entity_id"] == "A12"]
        self.assertGreaterEqual(len(rows), 6)
        for row in rows:
            self.assertTrue(row["at"], "transition missing timestamp")
            self.assertTrue(row["reason"], "transition missing reason")
            self.assertTrue(row["correlation_id"], "transition missing correlation id")


class HappyPathTests(Harness):
    def test_open_protect_close_reconcile(self):
        self._boot_flat()
        opened = self.orch.open_position("LONG", 0.01, intent_id="H1")
        self.assertTrue(opened["success"])
        self.assertEqual(
            self.ledger.get_intent("H1")["state"], IntentState.PROTECTED.value)
        # 仓位真实存在（保护单未触发，只是挂牌 ACTIVE）
        self.assertAlmostEqual(self.exchange.position("BTCUSDT").signed_qty, 0.01)
        closed = self.orch.close_position("take profit")
        self.assertTrue(closed["success"])
        close_intents = self.ledger.list_intents(states=[IntentState.RECONCILED.value])
        self.assertEqual(len(close_intents), 1)
        # 真正发出了 reduceOnly 平仓单
        closes = [r for r in self.exchange.submit_log
                  if r.order_kind == OrderKind.CLOSE and r.reduce_only]
        self.assertEqual(len(closes), 1)
        self.assertEqual(
            self.ledger.get_position_fact("BTCUSDT")["state"],
            PositionFactState.KNOWN_FLAT.value)

    def test_open_refused_while_position_open(self):
        self._boot_flat()
        self.orch.open_position("LONG", 0.01, intent_id="H2a")
        second = self.orch.open_position("SHORT", 0.01, intent_id="H2b")
        self.assertFalse(second["success"])
        self.assertIn("already open", second["reason"])
        self.assertEqual(len(self.entry_orders()), 1)


if __name__ == "__main__":
    unittest.main()
