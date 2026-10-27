"""S2-WIRE-FIX7（c623cd3 复审 R3-3 收尾）：不接管调用方事务。

评审两项独立复现：
1. 调用方已有未提交修改 + 升级因历史重复失败 → 拒绝必须在任何
   写入前；拒绝后调用方 rollback 有效，无半升级残留。
2. 调用方未提交 avg_price=123 + 成功追加重算 → 方法不得把外层
   事务一并提交；拒绝后 rollback，123 必须消失。

裁定（与 S1 一致的拒绝方案）：
- append_fill_recomputation / _ensure_recompute_schema 发现
  conn.in_transaction=True 在任何写入前拒绝；
- 快速路径（索引已在位）同样受前置条件约束；
- 不替调用方 commit/rollback，不改连接配置；
- 无外层事务时，既有幂等/并发/升级测试继续通过（回归锚定）。
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.kernel.ledger import Ledger
from aurora.p0_boundary import SafetyViolation


class F7Base(unittest.TestCase):
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
        self.addCleanup(self.led.close)

    def _append(self, led, **kw):
        params = dict(fill_id="F1", old_value=0.0, new_value=1.0,
                      reason="test", old_ctx="ctx-a", new_ctx="ctx-b",
                      basis_ref="order:C1")
        params.update(kw)
        return led.append_fill_recomputation(**params)

    def _cols(self):
        return {r[1] for r in self.led._conn.execute(
            "PRAGMA table_info(fill_recomputations)")}

    def _rollback(self):
        self.led._conn.rollback()


class CallerTransactionTests(F7Base):
    """评审复现 1：未提交修改 + 失败升级 → 拒绝且 rollback 有效。"""

    def test_open_txn_duplicate_upgrade_refused_then_rollback_clean(self):
        # 预置历史重复（升级必然失败的场景）
        c = self.led._conn
        c.execute(
            "CREATE TABLE fill_recomputations ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " fill_id TEXT NOT NULL, old_value REAL NOT NULL,"
            " new_value REAL NOT NULL, old_ctx TEXT, new_ctx TEXT,"
            " basis_ref TEXT, reason TEXT NOT NULL,"
            " recomputed_at TEXT NOT NULL)")
        for v in (1.0, 2.0):
            c.execute(
                "INSERT INTO fill_recomputations (fill_id, old_value,"
                " new_value, old_ctx, new_ctx, basis_ref, reason,"
                " recomputed_at) VALUES ('F1', 0, ?, 'a', 'b',"
                " 'order:C1', 'r', 't')", (v,))
        c.commit()
        # 调用方打开事务并留下未提交修改
        c.execute("BEGIN")
        c.execute(
            "UPDATE orders SET avg_price=123 WHERE client_order_id='C1'")
        self.assertTrue(c.in_transaction)
        with self.assertRaises(SafetyViolation) as cm:
            self._append(self.led)
        self.assertIn("open transaction", str(cm.exception))
        # 拒绝发生在任何写入前：调用方 rollback 有效
        self._rollback()
        avg = c.execute(
            "SELECT avg_price FROM orders"
            " WHERE client_order_id='C1'").fetchone()[0]
        self.assertNotEqual(avg, 123.0, "caller rollback must hold")
        # 无半升级残留：symbol 列/索引均缺席；历史重复原样
        self.assertNotIn("symbol", self._cols())
        idx = c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index'"
            " AND name='ux_fill_recompute_ident'").fetchone()
        self.assertIsNone(idx)
        self.assertEqual(
            c.execute("SELECT COUNT(*) FROM fill_recomputations"
                      ).fetchone()[0], 2)

    def test_open_txn_direct_schema_call_refused(self):
        # 直接调用升级入口同样拒绝（含首次升级路径）
        self.led._conn.execute("BEGIN")
        self.assertTrue(self.led._conn.in_transaction)
        with self.assertRaises(SafetyViolation):
            self.led._ensure_recompute_schema()
        self._rollback()

    def test_open_txn_fast_path_also_refused(self):
        # 快速路径（索引已在位）不得绕过事务前置条件
        self._append(self.led)  # 完成升级
        idx = self.led._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index'"
            " AND name='ux_fill_recompute_ident'").fetchone()
        self.assertIsNotNone(idx)
        c = self.led._conn
        c.execute("BEGIN")
        c.execute(
            "UPDATE orders SET avg_price=123 WHERE client_order_id='C1'")
        with self.assertRaises(SafetyViolation):
            self.led._ensure_recompute_schema()
        with self.assertRaises(SafetyViolation):
            self._append(self.led, old_ctx="x", new_ctx="y")
        self._rollback()
        avg = c.execute(
            "SELECT avg_price FROM orders"
            " WHERE client_order_id='C1'").fetchone()[0]
        self.assertNotEqual(avg, 123.0)


class CallerCommitIsolationTests(F7Base):
    """评审复现 2：方法不得把调用方未提交数据一并提交。"""

    def test_success_path_never_commits_caller_txn(self):
        c = self.led._conn
        c.execute("BEGIN")
        c.execute(
            "UPDATE orders SET avg_price=123 WHERE client_order_id='C1'")
        with self.assertRaises(SafetyViolation):
            self._append(self.led)
        self._rollback()
        avg = c.execute(
            "SELECT avg_price FROM orders"
            " WHERE client_order_id='C1'").fetchone()[0]
        self.assertNotEqual(avg, 123.0,
                            "method must not publish caller's"
                            " uncommitted changes")
        # 拒绝未产生任何重算记录
        self.assertEqual(self.led.fill_recomputations("F1"), [])
        # 外层事务结束后正常路径可用
        rid = self._append(self.led)
        self.assertEqual(len(self.led.fill_recomputations("F1")), 1)
        self.assertIsNotNone(rid)


class NoOuterTxnRegressionTests(F7Base):
    """无外层事务：幂等/并发/升级行为保持（回归锚定）。"""

    def test_idempotent_and_conflict_paths_unchanged(self):
        rid = self._append(self.led, old_value=0.0, new_value=1.0)
        rid2 = self._append(self.led, old_value=0.0, new_value=1.0)
        self.assertEqual(rid, rid2)
        from aurora.kernel.ledger import RecomputeIdentityConflict
        with self.assertRaises(RecomputeIdentityConflict):
            self._append(self.led, old_value=0.0, new_value=999.0)
        self.assertEqual(len(self.led.fill_recomputations("F1")), 1)

    def test_upgrade_and_clean_legacy_table_unchanged(self):
        # 干净旧表（无 symbol 列）升级成功且原子
        c = self.led._conn
        c.execute(
            "CREATE TABLE fill_recomputations ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " fill_id TEXT NOT NULL, old_value REAL NOT NULL,"
            " new_value REAL NOT NULL, old_ctx TEXT, new_ctx TEXT,"
            " basis_ref TEXT, reason TEXT NOT NULL,"
            " recomputed_at TEXT NOT NULL)")
        c.execute(
            "INSERT INTO fill_recomputations (fill_id, old_value,"
            " new_value, old_ctx, new_ctx, basis_ref, reason,"
            " recomputed_at) VALUES ('F1', 0, 1, 'a', 'b',"
            " 'order:C1', 'r', 't')")
        c.commit()
        self._append(self.led, old_ctx="c", new_ctx="d")
        self.assertIn("symbol", self._cols())
        idx = c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index'"
            " AND name='ux_fill_recompute_ident'").fetchone()
        self.assertIsNotNone(idx)

    def test_orchestrator_explicit_recompute_path_unchanged(self):
        # 生产调用路径无外层事务 → EXPLICIT_RECOMPUTE 不受影响
        from aurora.kernel import fill_migration as fm
        from aurora.kernel.fake_exchange import FakeExchange
        from aurora.kernel.orchestrator import Orchestrator
        from aurora.kernel.port import Fill
        self.led.close()
        fm.migrate_fills_identity(self.path)
        led = Ledger(self.path)
        self.addCleanup(led.close)
        orch = Orchestrator(led, FakeExchange(), instance_id="f7")
        orch.recover()
        # 腿结构在 recover 后建（避免恢复逻辑扫 SUBMITTING 腿触发
        # 终态迁移）
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
        led.update_order("I1-ENTRY", avg_price=105.0)
        f = Fill(fill_id="EVB", client_order_id="I1-SL1", qty=0.01,
                 price=99.0, fee=0.0, side="SELL", filled_at="t5",
                 symbol="BTCUSDT", qty_raw="0.01", price_raw="99.0",
                 fee_raw="0.0", fee_asset="USDT")
        out = orch.apply_fill_event(f)
        self.assertEqual(out["class"], "DUPLICATE")
        self.assertEqual(len(led.fill_recomputations("EVB")), 1)


if __name__ == "__main__":
    unittest.main()
