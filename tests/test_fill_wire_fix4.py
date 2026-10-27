"""S2 接线修正第四轮（ca031f1 复审四项阻断）：真实证明场景。

阻断 1（复合身份贯穿读写）：
  - insert_fill 一次性 INSERT 完整 EVENT 字段（不再先 INSERT 再按
    裸 fill_id UPDATE）；get_fill/fill_exists/冲突定位全部使用
    (symbol, fill_id) 复合身份。
阻断 2（两侧 EVENT 重放走 raw 校验）：
  - insert_fill 冲突分支按存储行 origin 分派 EVENT/HISTORY/混合，
    不再把两侧都包装成 HISTORY——raw 数值差不被 REAL 展示值抹平，
    REAL 展示差不制造伪冲突。
阻断 3（PnL 重算用冻结推导上下文）：
  - 存储行携带冻结 ctx（venue_derivation_ctx 随写）；重放按
    stored_ctx vs 当前基准 ctx 分派 DEVIATION / EXPLICIT_RECOMPUTE；
    缺 ctx = 不可证实（PNL_UNVERIFIABLE），绝不伪造空串为"同上下文"。
阻断 4（解析引用持久审计链）：
  - append_fill_recomputation 强制 old_ctx/new_ctx/basis_ref；
    clear_* 先落 resolution_log 再删标志（同事务）；机器引用
    （fill:/order:/fact:/recompute:）必须解析到已存在目标。
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.kernel import fill_migration as fm
from aurora.kernel.fake_exchange import FakeExchange
from aurora.kernel.ledger import FillIdentityConflict, Ledger
from aurora.kernel.orchestrator import Orchestrator
from aurora.kernel.port import Fill
from aurora.p0_boundary import SafetyViolation


class F4Base(unittest.TestCase):
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
        """S1 迁移库 + 新 Orchestrator（venue 路径可用）。"""
        self.led.close()
        fm.migrate_fills_identity(self.path)
        led = Ledger(self.path)
        self.addCleanup(led.close)
        orch = Orchestrator(led, FakeExchange(), instance_id="f4")
        orch.recover()
        return led, orch

    def _v(self, **kw):
        base = dict(fill_id="F1", client_order_id="C1", qty=0.25,
                    price=100.5, fee=0.0, side="BUY", filled_at="t1",
                    symbol="BTCUSDT", qty_raw="0.25",
                    price_raw="100.5", fee_raw="0.0",
                    fee_asset="USDT")
        base.update(kw)
        return Fill(**base)


class B1_CompositeIdentityTests(F4Base):
    """阻断 1：复合身份 (symbol, fill_id) 贯穿所有读写。"""

    def test_one_shot_insert_no_post_update(self):
        led, orch = self._s1()
        out = orch.apply_fill_event(
            self._v(fill_id="W4A", client_order_id="C1"))
        self.assertEqual(out["class"], "LATE_NEW_FILL")
        # 一次性写入：symbol/origin/raw/ctx 同行原子落库
        row = led._conn.execute(
            "SELECT symbol, origin, qty_raw, price_raw, fee_raw,"
            " fee_asset, derivation_ctx FROM fills"
            " WHERE fill_id='W4A' AND symbol='BTCUSDT'").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "BTCUSDT")
        self.assertEqual(row[1], "EVENT")
        self.assertEqual(row[2], "0.25")
        self.assertEqual(row[3], "100.5")
        self.assertEqual(row[4], "0.0")
        self.assertEqual(row[5], "USDT")
        self.assertIsNotNone(row[6], "derivation_ctx must ship with"
                             " the INSERT (frozen basis at write time)")

    def test_null_legacy_and_event_rows_coexist_by_identity(self):
        led, _ = self._s1()
        # F1 迁移后是 NULL-symbol LEGACY 行；同 fill_id 的 EVENT 行
        # 是不同身份——两者共存（复合 PK 语义）
        ok = led.insert_fill(
            "F1", "C1", 0.25, 100.5, 0, "BUY", "t1",
            venue_symbol="BTCUSDT", venue_qty_raw="0.25",
            venue_price_raw="100.5", venue_fee_raw="0.0",
            venue_fee_asset="USDT",
            venue_derivation_ctx="v1|basis=order:C1")
        self.assertTrue(ok, "different composite identity must insert")
        # 读取按完整身份分派：裸读命中 NULL-symbol LEGACY 行；
        # 带 symbol 命中 EVENT 行；不存在的 symbol 不命中
        bare = led.get_fill("F1")
        self.assertIsNone(bare["symbol"])
        self.assertEqual(bare["origin"], "LEGACY")
        self.assertEqual(
            led.get_fill("F1", symbol="BTCUSDT")["origin"], "EVENT")
        self.assertFalse(led.fill_exists("F1", symbol="ETHUSDT"))
        self.assertTrue(led.fill_exists("F1"))
        self.assertTrue(led.fill_exists("F1", symbol="BTCUSDT"))

    def test_conflict_localized_by_composite_key(self):
        led, _ = self._s1()
        led.insert_fill(
            "W4C", "C1", 0.25, 100.5, 0, "BUY", "t1",
            venue_symbol="BTCUSDT", venue_qty_raw="0.25",
            venue_price_raw="100.5", venue_fee_raw="0.0",
            venue_fee_asset="USDT", venue_derivation_ctx="ctx")
        # 同身份不同 raw → 冲突
        with self.assertRaises(FillIdentityConflict):
            led.insert_fill(
                "W4C", "C1", 0.25, 100.5, 0, "BUY", "t1",
                venue_symbol="BTCUSDT", venue_qty_raw="0.26",
                venue_price_raw="100.5", venue_fee_raw="0.0",
                venue_fee_asset="USDT", venue_derivation_ctx="ctx")
        # 不同 symbol = 不同身份 → 可入账（不误伤）
        ok = led.insert_fill(
            "W4C", "C1", 0.25, 100.5, 0, "BUY", "t1",
            venue_symbol="ETHUSDT", venue_qty_raw="0.26",
            venue_price_raw="100.5", venue_fee_raw="0.0",
            venue_fee_asset="USDT", venue_derivation_ctx="ctx")
        self.assertTrue(ok)


    def test_venue_replay_of_legacy_row_not_adopted_as_new(self):
        # 复合身份未命中 ≠ 新成交：同 fill_id 的 NULL-symbol 历史
        # 行是同一笔交易的审计定位 → 跨等级比较（INCOMPLETE）→
        # UNRESOLVED，绝不作为 (symbol, fill_id) 新身份收养
        led, orch = self._s1()
        out = orch.apply_fill_event(
            self._v(fill_id="F1", client_order_id="C1",
                    qty=0.25, qty_raw="0.25"))
        self.assertEqual(out["class"], "IDENTITY_UNRESOLVED")
        rows = led._conn.execute(
            "SELECT COUNT(*) FROM fills WHERE fill_id='F1'").fetchone()
        self.assertEqual(rows[0], 1, "no phantom second identity row")
        self.assertIn("F1", led.unresolved_fill_ids())


class B2_EventVsEventRawTests(F4Base):
    """阻断 2：两侧 EVENT 的重放用原始比较，不包装为 HISTORY。"""

    def test_raw_diff_behind_equal_reals_exposed(self):
        # raw 数值不同但 REAL 展示相同（0.1 的双精度世界）：
        # EVENT 校验按 raw → 冲突暴露；HISTORY 包装会吞掉它
        led, _ = self._s1()
        led.insert_fill(
            "W4R", "C1", 0.1, 100.5, 0, "BUY", "t1",
            venue_symbol="BTCUSDT",
            venue_qty_raw="0.1000000000000000055511151231257827",
            venue_price_raw="100.5", venue_fee_raw="0.0",
            venue_fee_asset="USDT", venue_derivation_ctx="ctx")
        with self.assertRaises(FillIdentityConflict) as cm:
            led.insert_fill(
                "W4R", "C1", 0.1, 100.5, 0, "BUY", "t1",
                venue_symbol="BTCUSDT", venue_qty_raw="0.1",
                venue_price_raw="100.5", venue_fee_raw="0.0",
                venue_fee_asset="USDT", venue_derivation_ctx="ctx")
        self.assertIn("qty", str(cm.exception))

    def test_equal_raws_with_display_noise_not_spurious_conflict(self):
        # raw 相同、REAL 展示带尾差：EVENT 校验以 raw 为准 → 幂等
        # False（HISTORY 包装会拿 float 制造伪冲突）
        led, _ = self._s1()
        led.insert_fill(
            "W4P", "C1", 0.25, 99.0, 0, "BUY", "t1",
            venue_symbol="BTCUSDT", venue_qty_raw="0.25",
            venue_price_raw="99.0", venue_fee_raw="0.0",
            venue_fee_asset="USDT", venue_derivation_ctx="ctx")
        ok = led.insert_fill(
            "W4P", "C1", 0.25, 99.00000000000001, 0, "BUY", "t1",
            venue_symbol="BTCUSDT", venue_qty_raw="0.25",
            venue_price_raw="99.0", venue_fee_raw="0.0",
            venue_fee_asset="USDT", venue_derivation_ctx="ctx")
        self.assertFalse(ok, "same raws = idempotent replay")

    def test_exact_replay_idempotent_false(self):
        led, _ = self._s1()
        args = ("W4E", "C1", 0.25, 100.5, 0, "BUY", "t1")
        kw = dict(venue_symbol="BTCUSDT", venue_qty_raw="0.25",
                  venue_price_raw="100.5", venue_fee_raw="0.0",
                  venue_fee_asset="USDT",
                  venue_derivation_ctx="ctx")
        self.assertTrue(led.insert_fill(*args, **kw))
        self.assertFalse(led.insert_fill(*args, **kw))


class B3_FrozenDerivationCtxTests(F4Base):
    """阻断 3：PnL 重算用冻结推导上下文（详见 test_fill_wire_fix3
    的三场景；此处做跨文件契约锚定）。"""

    def test_ctx_helper_is_frozen_entry_basis(self):
        led, orch = self._s1()
        led.record_order_submitting(
            client_order_id="I1-SL9", intent_id="I1",
            order_kind="SL", side="SELL", position_side="LONG",
            quantity=0.25, reduce_only=True)
        ctx = orch._pnl_derivation_ctx(led.get_order("I1-SL9"))
        self.assertIsNotNone(ctx)
        self.assertIn("I1-ENTRY", ctx)       # 基准 = entry 腿
        self.assertIn("entry_avg=", ctx)     # 基准值冻结
        # 基准变化 → ctx 变化（推导上下文跟基准走，不跟当前订单漂移）
        led.record_order_submitting(
            client_order_id="I1-ENTRY", intent_id="I1",
            order_kind="ENTRY", side="BUY", position_side="LONG",
            quantity=0.25)
        led.update_order("I1-ENTRY", avg_price=100.5)
        self.assertNotEqual(
            ctx, orch._pnl_derivation_ctx(led.get_order("I1-SL9")))
        # 无订单 → 无上下文（不伪造）
        self.assertIsNone(orch._pnl_derivation_ctx(None))

    def test_venue_row_carries_ctx_at_write(self):
        led, orch = self._s1()
        out = orch.apply_fill_event(
            self._v(fill_id="W4X", client_order_id="C1"))
        self.assertEqual(out["class"], "LATE_NEW_FILL")
        row = led.get_fill("W4X", symbol="BTCUSDT")
        self.assertIsNotNone(row.get("derivation_ctx"))
        self.assertIn("basis=order:I1-ENTRY", row["derivation_ctx"])


class B4_ResolutionAuditTrailTests(F4Base):
    """阻断 4：解析引用形成持久审计链。"""

    def test_recomputation_requires_frozen_basis_triple(self):
        for kwargs in ({}, {"old_ctx": "a"}, {"old_ctx": "a",
                                              "new_ctx": "b"}):
            with self.assertRaises(SafetyViolation):
                self.led.append_fill_recomputation(
                    "F1", 0.0, 0.1, "incomplete basis", **kwargs)

    def test_clear_unresolved_logs_resolution_then_deletes(self):
        self.led.mark_fill_unresolved("F1", "missing facts ['symbol']")
        self.led.clear_fill_unresolved(
            "F1", resolution_ref="operator-disposition-2026-10-25")
        self.assertNotIn("F1", self.led.unresolved_fill_ids())
        recs = self.led.resolution_records(kind="unresolved_cleared")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["entity_id"], "F1")
        self.assertEqual(
            recs[0]["resolution_ref"],
            "operator-disposition-2026-10-25")
        self.assertIn("missing facts", recs[0]["detail"])
        # 审计链跨重启持久
        self.led.close()
        led2 = Ledger(self.path)
        self.addCleanup(led2.close)
        self.assertEqual(
            len(led2.resolution_records(kind="unresolved_cleared")), 1)

    def test_machine_refs_must_resolve(self):
        led, _ = self._s1()
        led.insert_fill(
            "W4M", "C1", 0.25, 100.5, 0, "BUY", "t1",
            venue_symbol="BTCUSDT", venue_qty_raw="0.25",
            venue_price_raw="100.5", venue_fee_raw="0.0",
            venue_fee_asset="USDT", venue_derivation_ctx="ctx")
        led.record_reconciliation_fact("FACT1", "C1", ["W4M"], 0.25)
        rid = led.append_fill_recomputation(
            "F1", 0.0, 0.1, "test", old_ctx="a", new_ctx="b",
            basis_ref="order:C1")
        # 悬空机器引用 → 拒绝
        for bad in ("fill:BTCUSDT:GONE", "fill:W4M",  # 裸 id 禁止
                    "order:NOPE", "fact:NOPE", "recompute:99999",
                    "recomputation-event:99999"):
            with self.assertRaises(SafetyViolation):
                led._validate_resolution_ref(bad)
        # 可解析机器引用 → 接受
        for good in ("fill:BTCUSDT:W4M", "order:C1", "fact:FACT1",
                     f"recompute:{rid}", f"recomputation-event:{rid}"):
            self.assertEqual(led._validate_resolution_ref(good), good)
        # 人工复合注记（含空格）→ 接受为处置文本
        self.assertEqual(
            led._validate_resolution_ref("order:C1 fill:BTCUSDT:W4M"),
            "order:C1 fill:BTCUSDT:W4M")

    def test_basis_ref_machine_dangling_rejected_on_append(self):
        with self.assertRaises(SafetyViolation):
            self.led.append_fill_recomputation(
                "F1", 0.0, 0.1, "dangling basis",
                old_ctx="a", new_ctx="b", basis_ref="order:NOPE")
        # 未落任何记录
        self.assertEqual(self.led.fill_recomputations("F1"), [])


if __name__ == "__main__":
    unittest.main()
