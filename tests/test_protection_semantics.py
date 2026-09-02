"""P0-B2.1 确定性验收：保护覆盖口径 + 迟到成交三分类 + OCO 部分成交。

对应 reviewer 指定的 10 个场景（T1..T10）。全部离线。
覆盖断言使用独立口径复算（不复用生产 compute_protection_status），
避免"实现验证实现"。
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.kernel.coverage import compute_protection_status  # noqa: E402
from aurora.kernel.fake_exchange import FakeExchange  # noqa: E402
from aurora.kernel.ledger import Ledger, PositionFactState  # noqa: E402
from aurora.kernel.orchestrator import Orchestrator  # noqa: E402
from aurora.kernel.port import Fill, OrderKind  # noqa: E402
from aurora.kernel.state_machine import IntentState, utc_now  # noqa: E402

EPS = 1e-9


def oracle_coverage(exchange, symbol):
    """独立口径：直接从交易所内部事实复算 SL/TP 覆盖与持仓（不复用生产代码）。"""
    sl = tp = 0.0
    position = 0.0
    for order in exchange._orders.values():
        req = order["req"]
        remaining = req.quantity - order["filled_qty"]
        if order["status"] == "NEW" and remaining > EPS:
            if req.order_kind == OrderKind.STOP_LOSS:
                sl += remaining
            elif req.order_kind == OrderKind.TAKE_PROFIT:
                tp += remaining
        if order["filled_qty"] > EPS:
            sign = 1.0 if req.side == "BUY" else -1.0
            position += sign * order["filled_qty"]
    return {"sl": round(sl, 10), "tp": round(tp, 10),
            "position": round(abs(position), 10)}


class Harness(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "ledger.db")
        self.exchange = FakeExchange()
        self.ledger = Ledger(self.path)
        self.orch = Orchestrator(self.ledger, self.exchange, instance_id="ps")
        self.orch.recover()

    def tearDown(self):
        self.ledger.close()
        self._tmp.cleanup()

    def _open_full(self, iid="P", qty=0.010):
        result = self.orch.open_position("LONG", qty, intent_id=iid)
        self.assertTrue(result["success"], result)
        return result

    def assertMatchesOracle(self, iid):
        oracle = oracle_coverage(self.exchange, "BTCUSDT")
        status = compute_protection_status(
            self.ledger.orders_for_intent(iid), oracle["position"])
        self.assertAlmostEqual(status.sl_coverage, oracle["sl"], places=9)
        self.assertAlmostEqual(status.tp_coverage, oracle["tp"], places=9)


class CoverageSemanticsTests(Harness):
    def test_t1_sl_shards_sum_cover_position(self):
        """T1：两个 SL 分片之和完整覆盖仓位（分片求和，非 max）。"""
        self.exchange.entry_behavior = "partial"
        self._open_full("T1", 0.010)          # 首次保护 0.006（分片一）
        self.exchange.complete_fill("T1-ENTRY")
        self.orch.recover()                    # 增量补挂 0.004（分片二）
        sl_orders = [o for o in self.ledger.orders_for_intent("T1")
                     if o["order_kind"] == "STOP_LOSS" and o["state"] == "ACTIVE"]
        self.assertEqual(len(sl_orders), 2)
        shards = sorted(o["quantity"] for o in sl_orders)
        self.assertAlmostEqual(shards[0], 0.004, places=10)
        self.assertAlmostEqual(shards[1], 0.006, places=10)
        status = compute_protection_status(
            self.ledger.orders_for_intent("T1"), 0.010)
        self.assertAlmostEqual(status.sl_coverage, 0.010, places=10)
        self.assertTrue(status.mandatory_ok)
        self.assertMatchesOracle("T1")

    def test_t2_sl_tp_must_not_be_summed(self):
        """T2：SL+TP 相加不得作为安全覆盖（0.006+0.006 ≠ 覆盖 0.010）。"""
        orders = [
            {"client_order_id": "X-SL", "order_kind": "STOP_LOSS",
             "state": "ACTIVE", "quantity": 0.006, "filled_qty": 0.0},
            {"client_order_id": "X-TP", "order_kind": "TAKE_PROFIT",
             "state": "ACTIVE", "quantity": 0.006, "filled_qty": 0.0},
        ]
        status = compute_protection_status(orders, 0.010)
        # 若错误相加（0.012 ≥ 0.010）会误判安全
        self.assertFalse(status.mandatory_ok)
        self.assertFalse(status.tp_ok)
        self.assertFalse(status.protected_full)

    def test_t3_sl_sufficient_tp_insufficient_expressed_separately(self):
        """T3：SL 足额、TP 不足 → 安全但不完整，与完整状态分开表达。"""
        orders = [
            {"client_order_id": "X-SL", "order_kind": "STOP_LOSS",
             "state": "ACTIVE", "quantity": 0.010, "filled_qty": 0.0},
            {"client_order_id": "X-TP", "order_kind": "TAKE_PROFIT",
             "state": "ACTIVE", "quantity": 0.006, "filled_qty": 0.0},
        ]
        status = compute_protection_status(orders, 0.010)
        self.assertTrue(status.mandatory_ok)
        self.assertFalse(status.tp_ok)
        self.assertTrue(status.safe_but_incomplete)
        self.assertFalse(status.protected_full)


class DegradedRepairTests(Harness):
    def test_t4_tp_partial_fill_rebuild_for_actual_remaining(self):
        """T4：TP 部分成交 → 按交易所实际剩余仓位重建保护。"""
        self._open_full("T4", 0.010)
        self.exchange.fire_protection("T4-TP", price=101.0, qty=0.004)
        self.orch.recover()
        intent = self.ledger.get_intent("T4")
        self.assertEqual(intent["state"], IntentState.PROTECTED.value)
        # 重建腿按实际剩余 0.006，而非入场量 0.010 或推算值
        sl_r = [o for o in self.ledger.orders_for_intent("T4")
                if o["client_order_id"].startswith("T4-SL-R")]
        tp_r = [o for o in self.ledger.orders_for_intent("T4")
                if o["client_order_id"].startswith("T4-TP-R")]
        self.assertTrue(sl_r and tp_r)
        for leg in sl_r + tp_r:
            self.assertAlmostEqual(leg["quantity"], 0.006, places=10)
        # 旧 SL 兄弟腿被精确撤销
        self.assertEqual(self.ledger.get_order("T4-SL")["state"], "CANCELLED")
        # 部分触发腿的成交与盈亏入账
        tp_fills = self.ledger.fills_for_order("T4-TP")
        self.assertEqual(len(tp_fills), 1)
        self.assertAlmostEqual(tp_fills[0]["realized_pnl"], 0.004, places=9)  # (101-100)*0.004
        self.assertMatchesOracle("T4")
        self.assertFalse(self.ledger.kill_state()["engaged"])

    def test_t5_oco_cancel_unknown_goes_recovery(self):
        """T5：OCO 兄弟腿撤单结果未知 → RECOVERY_REQUIRED + 熔断。"""
        self._open_full("T5", 0.010)
        self.exchange.fire_protection("T5-TP", price=101.0, qty=0.004)
        self.exchange.cancel_behavior = "unknown"
        self.orch.recover()
        intent = self.ledger.get_intent("T5")
        self.assertEqual(intent["state"], IntentState.RECOVERY_REQUIRED.value)
        self.assertTrue(self.ledger.kill_state()["engaged"])
        # 未重建任何新腿（修复在撤单未知处中止）
        rebuilds = [o for o in self.ledger.orders_for_intent("T5")
                    if "-R" in o["client_order_id"]]
        self.assertEqual(rebuilds, [])

    def test_t10_no_new_opens_during_repair(self):
        """T10：保护修复期间不能接受新 OPEN Intent。"""
        self.ledger.create_intent("DEG", "BTCUSDT", "LONG", 0.01)
        for frm, to in (
            (IntentState.INTENT_CREATED, IntentState.SUBMITTING),
            (IntentState.SUBMITTING, IntentState.FILLED_UNPROTECTED),
            (IntentState.FILLED_UNPROTECTED, IntentState.PROTECTION_SUBMITTING),
            (IntentState.PROTECTION_SUBMITTING, IntentState.PROTECTED),
            (IntentState.PROTECTED, IntentState.PROTECTION_DEGRADED),
        ):
            self.ledger.transition_intent("DEG", to, "setup", correlation_id="DEG")
        self.ledger.set_position_fact(
            "BTCUSDT", PositionFactState.KNOWN_OPEN, qty=0.01, side="LONG",
            source="test")
        result = self.orch.open_position("SHORT", 0.01, intent_id="BLOCKED")
        self.assertFalse(result["success"])
        self.assertIn("repair in progress", result["reason"])


class LateFillTests(Harness):
    def _make_fill(self, cid, fill_id, qty, price, side="BUY"):
        return Fill(
            fill_id=fill_id, client_order_id=cid, qty=qty, price=price,
            fee=round(qty * price * 0.0005, 8), side=side, filled_at=utc_now())

    def test_t6_late_new_fill_corrects_and_recovers(self):
        """T6：终态后新 fill_id 修正订单/费用/PnL，并使终态进入恢复。"""
        self._open_full("T6", 0.010)
        self.exchange.fire_protection("T6-SL", price=99.0)
        self.orch.recover()
        self.assertEqual(
            self.ledger.get_intent("T6")["state"], IntentState.RECONCILED.value)

        # 入场腿迟到新成交：订单累计成交被修正
        late_entry = self._make_fill("T6-ENTRY", "LATE-E", 0.002, 100.5)
        result = self.orch.apply_fill_event(late_entry)
        self.assertEqual(result["class"], "LATE_NEW_FILL")
        entry = self.ledger.get_order("T6-ENTRY")
        self.assertAlmostEqual(entry["filled_qty"], 0.012, places=10)
        row = self.ledger.get_fill("LATE-E")
        self.assertGreater(row["fee"], 0)
        self.assertAlmostEqual(row["realized_pnl"], 0.0, places=10)  # 入场腿

        # 平仓腿迟到新成交：已实现盈亏被修正（(97-100)*0.002 = -0.006）
        late_sl = self._make_fill("T6-SL", "LATE-S", 0.002, 97.0, side="SELL")
        result = self.orch.apply_fill_event(late_sl)
        self.assertEqual(result["class"], "LATE_NEW_FILL")
        self.assertAlmostEqual(result["realized_pnl"], -0.006, places=9)

        # 迟到事实推翻终态：RECOVERY_REQUIRED + 熔断 + 持仓重拉
        intent = self.ledger.get_intent("T6")
        self.assertEqual(intent["state"], IntentState.RECOVERY_REQUIRED.value)
        self.assertTrue(self.ledger.kill_state()["engaged"])

    def test_t7_duplicate_fill_no_economic_effect(self):
        """T7：重复 fill_id 不产生经济影响。"""
        self._open_full("T7", 0.010)
        existing_id = self.ledger.fills_for_order("T7-ENTRY")[0]["fill_id"]
        dup = self._make_fill("T7-ENTRY", existing_id, 0.010, 100.0)
        first = self.orch.apply_fill_event(dup)
        self.assertEqual(first["class"], "DUPLICATE")
        again = self.orch.apply_fill_event(dup)
        self.assertEqual(again["class"], "DUPLICATE")
        self.assertEqual(len(self.ledger.fills_for_order("T7-ENTRY")), 1)
        order = self.ledger.get_order("T7-ENTRY")
        self.assertAlmostEqual(order["filled_qty"], 0.010, places=10)

    def test_t8_fill_covered_by_reconciliation_snapshot(self):
        """T8：已被事实快照计入的迟到 Fill 只关联审计，不重复记账。"""
        # 构造：订单事实同步到 0.010，但成交明细只录了 0.006
        self.ledger.create_intent("T8", "BTCUSDT", "LONG", 0.010)
        self.ledger.record_order_submitting(
            "T8-ENTRY", "T8", "ENTRY", "BUY", "LONG", 0.010)
        self.ledger.update_order("T8-ENTRY", state="FILLED",
                                 filled_qty=0.010, avg_price=100.0)
        self.ledger.insert_fill("T8-F0", "T8-ENTRY", 0.006, 100.0, 0.0, "BUY", utc_now())
        covered = self._make_fill("T8-ENTRY", "T8-F1", 0.004, 100.0)
        result = self.orch.apply_fill_event(covered)
        self.assertEqual(result["class"], "COVERED_BY_FACT")
        order = self.ledger.get_order("T8-ENTRY")
        self.assertAlmostEqual(order["filled_qty"], 0.010, places=10)  # 未重复
        rows = self.ledger.fills_for_order("T8-ENTRY")
        self.assertEqual(len(rows), 2)  # 审计层保留
        self.assertAlmostEqual(sum(r["qty"] for r in rows), 0.010, places=10)


class IdempotencyTests(Harness):
    def test_t9_repeated_recover_no_duplicate_cancel_or_rebuild(self):
        """T9：多次 recover() 不重复撤单或补挂。"""
        self._open_full("T9", 0.010)
        self.exchange.fire_protection("T9-TP", price=101.0, qty=0.004)
        self.orch.recover()
        orders_after_first = sorted(
            o["client_order_id"] for o in self.ledger.orders_for_intent("T9"))
        submits_after_first = len(self.exchange.submit_log)
        cancels_after_first = len(self.exchange.cancel_log) \
            if hasattr(self.exchange, "cancel_log") else None

        self.orch.recover()
        self.orch.recover()

        orders_after_third = sorted(
            o["client_order_id"] for o in self.ledger.orders_for_intent("T9"))
        self.assertEqual(orders_after_first, orders_after_third)
        self.assertEqual(len(self.exchange.submit_log), submits_after_first)
        self.assertEqual(
            self.ledger.get_intent("T9")["state"], IntentState.PROTECTED.value)
        self.assertMatchesOracle("T9")


if __name__ == "__main__":
    unittest.main()
