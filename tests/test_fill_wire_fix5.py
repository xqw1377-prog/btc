"""S2-WIRE-FIX5（d46abb8 复审四项）：评审独立复现场景的逐项关闭。

R1 legacy-shadow 显式 NULL 行查询：
  BTC EVENT 行先写入 → NULL LEGACY 行后写入 → 同 trade ID 的
  ETH 事件不得因裸 ID 探测命中 BTC 行而漏掉 NULL 历史行、也不得
  作为第三身份收养。shadow 探测必须显式查 NULL-symbol 行，
  结果不受插入顺序影响。
R2 对账覆盖按订单归属核验：
  BTC 订单 C1 的 fact 覆盖 trade ID X；ETH 订单 C2 的独立成交
  同 trade ID X → 不得套用 C1 的 fact（否则 economic_effect=0
  漏记 C2 经济影响）。
R3 重算事件稳定身份 + 幂等：
  相同（完整成交身份 + old/new ctx + 依据）的重放零新增；
  重算表保留完整成交引用（symbol 列）。
R4 机器引用不得附加文字降级：
  "order:NO_SUCH_ORDER plus explanation" 拒绝；说明走 detail。
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.kernel import fill_migration as fm
from aurora.kernel.fake_exchange import FakeExchange
from aurora.kernel.ledger import Ledger
from aurora.kernel.orchestrator import Orchestrator
from aurora.kernel.port import Fill
from aurora.p0_boundary import SafetyViolation


class F5Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "l.db")
        led = Ledger(self.path)
        led.create_intent("I1", "BTCUSDT", "LONG", 0.25)
        led.record_order_submitting(
            client_order_id="C1", intent_id="I1", order_kind="ENTRY",
            side="BUY", position_side="LONG", quantity=0.25)
        led.insert_fill("F1", "C1", 0.25, 100.5, 0.0, "BUY", "t1")
        self.led = led
        self.addCleanup(led.close)

    def _s1(self):
        self.led.close()
        fm.migrate_fills_identity(self.path)
        led = Ledger(self.path)
        self.addCleanup(led.close)
        orch = Orchestrator(led, FakeExchange(), instance_id="f5")
        orch.recover()
        return led, orch

    def _fill(self, **kw):
        base = dict(fill_id="X1", client_order_id="C1", qty=0.25,
                    price=100.5, fee=0.0, side="BUY", filled_at="t1",
                    symbol="BTCUSDT", qty_raw="0.25",
                    price_raw="100.5", fee_raw="0.0",
                    fee_asset="USDT")
        base.update(kw)
        return Fill(**base)


class R1_ShadowProbeOrderIndependentTests(F5Base):
    """R1：shadow 探测显式查 NULL 行，不受插入顺序影响。"""

    def _scenario(self):
        """BTC EVENT 行先写、NULL LEGACY 行后写（评审构造）。"""
        led, orch = self._s1()
        led.insert_fill(  # BTC EVENT 行（先）
            "TID", "C1", 0.25, 100.5, 0, "BUY", "t1",
            venue_symbol="BTCUSDT", venue_qty_raw="0.25",
            venue_price_raw="100.5", venue_fee_raw="0.0",
            venue_fee_asset="USDT", venue_derivation_ctx="ctx-btc")
        led.insert_fill(  # NULL-symbol LEGACY 行（后）
            "TID", "C1", 0.25, 100.5, 0, "BUY", "t1")
        # ETH 订单（归属合法，事件 symbol=ETHUSDT）
        led.create_intent("I2", "ETHUSDT", "LONG", 0.25)
        led.record_order_submitting(
            client_order_id="C2", intent_id="I2", order_kind="ENTRY",
            side="BUY", position_side="LONG", quantity=0.25)
        return led, orch

    def test_get_legacy_fill_returns_null_row_regardless_of_order(self):
        led, _ = self._scenario()
        legacy = led.get_legacy_fill("TID")
        self.assertIsNotNone(legacy)
        self.assertIsNone(legacy["symbol"])
        self.assertEqual(legacy["origin"], "LEGACY")
        # 裸读命中任意一行（可能 EVENT）；显式查询必须确定
        self.assertEqual(led.get_fill("TID")["origin"], "EVENT")  # 先插的 BTC 行

    def test_eth_event_not_adopted_shadow_still_found(self):
        led, orch = self._scenario()
        out = orch.apply_fill_event(self._fill(
            fill_id="TID", client_order_id="C2", symbol="ETHUSDT"))
        # 不作为第三身份收养：NULL 历史行被显式定位 → 跨等级比较
        # → 数值/symbol 不可证实 → UNRESOLVED（离冲突则 CONFLICT）
        self.assertIn(out["class"],
                      ("IDENTITY_UNRESOLVED", "IDENTITY_CONFLICT"))
        self.assertNotEqual(out["class"], "LATE_NEW_FILL")
        rows = led._conn.execute(
            "SELECT COUNT(*) FROM fills WHERE fill_id='TID'").fetchone()
        self.assertEqual(rows[0], 2, "no third identity row")

    def test_reverse_insertion_order_same_outcome(self):
        # NULL 行先写、BTC EVENT 后写 → 同样结果（不受顺序影响）
        led, orch = self._s1()
        led.insert_fill("TID", "C1", 0.25, 100.5, 0, "BUY", "t1")  # NULL 先
        led.insert_fill(  # BTC EVENT 后
            "TID", "C1", 0.25, 100.5, 0, "BUY", "t1",
            venue_symbol="BTCUSDT", venue_qty_raw="0.25",
            venue_price_raw="100.5", venue_fee_raw="0.0",
            venue_fee_asset="USDT", venue_derivation_ctx="ctx-btc")
        led.create_intent("I2", "ETHUSDT", "LONG", 0.25)
        led.record_order_submitting(
            client_order_id="C2", intent_id="I2", order_kind="ENTRY",
            side="BUY", position_side="LONG", quantity=0.25)
        out = orch.apply_fill_event(self._fill(
            fill_id="TID", client_order_id="C2", symbol="ETHUSDT"))
        self.assertIn(out["class"],
                      ("IDENTITY_UNRESOLVED", "IDENTITY_CONFLICT"))
        self.assertNotEqual(out["class"], "LATE_NEW_FILL")
        rows = led._conn.execute(
            "SELECT COUNT(*) FROM fills WHERE fill_id='TID'").fetchone()
        self.assertEqual(rows[0], 2)


class R2_CoverageOrderScopedTests(F5Base):
    """R2：对账覆盖证据按订单归属核验。"""

    def _two_symbol_orders(self, led):
        led.create_intent("I2", "ETHUSDT", "LONG", 0.25)
        led.record_order_submitting(
            client_order_id="C2", intent_id="I2", order_kind="ENTRY",
            side="BUY", position_side="LONG", quantity=0.25)

    def test_cross_order_same_trade_id_not_covered(self):
        led, orch = self._s1()
        self._two_symbol_orders(led)
        # BTC 订单 C1 的 fact 覆盖 trade ID "COV"
        led.record_reconciliation_fact("BF", "C1", ["COV"], 0.25)
        # ETH 订单 C2 收到同 trade ID 的独立成交
        out = orch.apply_fill_event(self._fill(
            fill_id="COV", client_order_id="C2", symbol="ETHUSDT",
            qty_raw="0.25", price_raw="100.5"))
        self.assertNotEqual(
            out["class"], "COVERED_BY_FACT",
            "another order's fact must not cover this fill")
        # 经济影响未被豁免：行存在且 economic_effect_applied=1
        row = led.get_fill("COV", symbol="ETHUSDT")
        self.assertIsNotNone(row)
        self.assertEqual(row["economic_effect_applied"], 1)
        # 同订单的覆盖引用仍然有效
        self.assertEqual(
            led.evidence_covers_fill("COV", client_order_id="C1"), "BF")
        self.assertIsNone(
            led.evidence_covers_fill("COV", client_order_id="C2"))

    def test_evidence_without_order_scope_fails_closed(self):
        led, _ = self._s1()
        led.record_reconciliation_fact("BF", "C1", ["COV"], 0.25)
        # 未提供订单归属 → 无证据（fail-closed，不再全表裸 ID 匹配）
        self.assertIsNone(led.evidence_covers_fill("COV"))

    def test_same_order_coverage_still_works(self):
        led, orch = self._s1()
        led.record_reconciliation_fact("BF", "C1", ["COV"], 0.25)
        out = orch.apply_fill_event(self._fill(
            fill_id="COV", client_order_id="C1"))
        self.assertEqual(out["class"], "COVERED_BY_FACT")
        self.assertEqual(out["evidence_fact_id"], "BF")
        row = led.get_fill("COV", symbol="BTCUSDT")
        self.assertEqual(row["economic_effect_applied"], 0)


class R3_RecomputeIdentityTests(F5Base):
    """R3：重算事件稳定身份（完整成交身份 + ctx 对 + 依据）。"""

    def test_identical_replay_appends_nothing(self):
        led, orch = self._s1()
        # 构造基准变化路径：EVB 冻结 ctx → 入场均价变化 → 重放两次
        led.record_order_submitting(
            client_order_id="I1-ENTRY", intent_id="I1",
            order_kind="ENTRY", side="BUY", position_side="LONG",
            quantity=0.25)
        led.record_order_submitting(
            client_order_id="I1-SL1", intent_id="I1",
            order_kind="SL", side="SELL", position_side="LONG",
            quantity=0.25, reduce_only=True)
        led.update_order("I1-ENTRY", avg_price=100.0)
        led.insert_fill(
            "EVB", "I1-SL1", 0.01, 99.0, 0, "SELL", "t5",
            realized_pnl=-0.01,
            venue_symbol="BTCUSDT", venue_qty_raw="0.01",
            venue_price_raw="99.0", venue_fee_raw="0.0",
            venue_fee_asset="USDT",
            venue_derivation_ctx=orch._pnl_derivation_ctx(
                led.get_order("I1-SL1")))
        led.update_order("I1-ENTRY", avg_price=105.0)  # 依据变化
        f = self._fill(fill_id="EVB", client_order_id="I1-SL1",
                       qty=0.01, qty_raw="0.01",
                       price=99.0, price_raw="99.0", side="SELL")
        out1 = orch.apply_fill_event(f)
        out2 = orch.apply_fill_event(f)
        self.assertEqual(out1["class"], "DUPLICATE")
        self.assertEqual(out2["class"], "DUPLICATE")
        recs = led.fill_recomputations("EVB")
        self.assertEqual(
            len(recs), 1,
            "identical basis-change replay must not append a second"
            " recomputation event")
        # 真正的新依据（basis 再变）→ 追加第二条
        led.update_order("I1-ENTRY", avg_price=110.0)
        orch.apply_fill_event(f)
        self.assertEqual(len(led.fill_recomputations("EVB")), 2)

    def test_recompute_table_keeps_full_fill_reference(self):
        led, _ = self._s1()
        led.insert_fill(
            "RB", "C1", 0.25, 100.5, 0, "BUY", "t1",
            venue_symbol="BTCUSDT", venue_qty_raw="0.25",
            venue_price_raw="100.5", venue_fee_raw="0.0",
            venue_fee_asset="USDT", venue_derivation_ctx="ctx")
        led.append_fill_recomputation(
            "RB", 0.0, 0.1, "basis change", old_ctx="a", new_ctx="b",
            basis_ref="order:C1", symbol="BTCUSDT")
        recs = led.fill_recomputations("RB")
        self.assertEqual(recs[0]["symbol"], "BTCUSDT")

    def test_cross_symbol_same_fill_id_recomputation_distinct(self):
        led, _ = self._s1()
        for sym in ("BTCUSDT", "ETHUSDT"):
            led.insert_fill(
                "RX", "C1", 0.25, 100.5, 0, "BUY", "t1",
                venue_symbol=sym, venue_qty_raw="0.25",
                venue_price_raw="100.5", venue_fee_raw="0.0",
                venue_fee_asset="USDT", venue_derivation_ctx="ctx")
        # 同 fill_id、不同 symbol、同 ctx 三元组 → 两条独立记录
        for sym in ("BTCUSDT", "ETHUSDT"):
            led.append_fill_recomputation(
                "RX", 0.0, 0.1, "basis change",
                old_ctx="a", new_ctx="b", basis_ref="order:C1",
                symbol=sym)
        self.assertEqual(len(led.fill_recomputations("RX")), 2)


class R4_MachineRefNoTextBypassTests(F5Base):
    """R4：机器引用附加文字不得降级为人工依据。"""

    def test_order_ref_with_explanation_rejected(self):
        led, _ = self._s1()
        led.record_order_submitting(
            client_order_id="EXIT", intent_id="I1", order_kind="SL",
            side="SELL", position_side="LONG", quantity=0.25,
            reduce_only=True)
        led.mark_fill_unresolved("EXIT", "test unresolved")
        # 评审原话复现：悬空 order 引用 + 文字说明 → 必须拒绝
        with self.assertRaises(SafetyViolation):
            led.clear_fill_unresolved(
                "EXIT",
                resolution_ref="order:NO_SUCH_ORDER plus explanation")
        # 仍处于 unresolved（未解除）
        self.assertIn("EXIT", led.unresolved_fill_ids())
        # 正确写法：可解析机器引用 + detail 说明
        led.clear_fill_unresolved(
            "EXIT", resolution_ref="order:EXIT",
            detail="protection leg order re-verified")
        self.assertNotIn("EXIT", led.unresolved_fill_ids())

    def test_resolvable_ref_with_trailing_text_also_rejected(self):
        # 即使目标存在，机器引用 + 附加文字 = 格式非法（拒绝）
        led, _ = self._s1()
        with self.assertRaises(SafetyViolation):
            led._validate_resolution_ref("order:C1 plus explanation")
        with self.assertRaises(SafetyViolation):
            led._validate_resolution_ref("order:")
        # 无机器前缀的自由文本仍可用（人工处置）
        self.assertEqual(
            led._validate_resolution_ref("manual operator disposition"),
            "manual operator disposition")

    def test_basis_ref_text_bypass_rejected_on_append(self):
        led, _ = self._s1()
        with self.assertRaises(SafetyViolation):
            led.append_fill_recomputation(
                "F1", 0.0, 0.1, "text bypass attempt",
                old_ctx="a", new_ctx="b",
                basis_ref="order:NOPE with note")
        self.assertEqual(led.fill_recomputations("F1"), [])


if __name__ == "__main__":
    unittest.main()
