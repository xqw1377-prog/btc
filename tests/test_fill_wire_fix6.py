"""S2-WIRE-FIX6（43f6fd5 复审 R3 三项残留）：逐项关闭。

R3-1 同身份异容必须显式冲突：
  相同 (symbol, fill_id, old_ctx, new_ctx, basis_ref) 但金额不同
  → RecomputeIdentityConflict，原记录保留，不得静默返回成功。
R3-2 并发一致重放收敛：
  查重后、插入前的竞态窗口由唯一索引兜底——捕获**本目标索引**
  冲突后重读比较内容：一致返回同一 id；异容报告冲突；其他异常
  上抛。
R3-3 既有重复记录的原子升级边界：
  历史同身份重复存在时升级明确阻断（列明冲突组，绝不删除/合并
  历史事件）；补列/索引/版本标记同一事务，失败整体回滚，
  无半升级。
"""
import os
import sys
import sqlite3
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.kernel.fake_exchange import FakeExchange
from aurora.kernel.ledger import (
    Ledger, RecomputeIdentityConflict,
)
from aurora.kernel.orchestrator import Orchestrator
from aurora.p0_boundary import SafetyViolation


class F6Base(unittest.TestCase):
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
        self.orch = Orchestrator(
            self.led, FakeExchange(), instance_id="f6")
        self.orch.recover()

    def _append(self, led, old=0.0, new=1.0, **kw):
        params = dict(fill_id="F1", old_value=old, new_value=new,
                      reason="test", old_ctx="ctx-a", new_ctx="ctx-b",
                      basis_ref="order:C1")
        params.update(kw)
        return led.append_fill_recomputation(**params)


class R3_1_SameIdentityDifferentAmounts(F6Base):
    """同身份异容：显式冲突，原记录保留。"""

    def test_same_identity_different_amounts_conflicts(self):
        rid = self._append(self.led, old=0.0, new=1.0)
        self.assertEqual(rid, 1)
        with self.assertRaises(RecomputeIdentityConflict) as cm:
            self._append(self.led, old=0.0, new=999.0)
        msg = str(cm.exception)
        self.assertIn("999", msg)
        self.assertIn("F1", msg)
        # 原记录保留且未被改写
        recs = self.led.fill_recomputations("F1")
        self.assertEqual(len(recs), 1)
        self.assertAlmostEqual(recs[0]["old_value"], 0.0)
        self.assertAlmostEqual(recs[0]["new_value"], 1.0)
        self.assertEqual(recs[0]["id"], rid)

    def test_identical_replay_still_idempotent(self):
        rid = self._append(self.led, old=0.0, new=1.0)
        rid2 = self._append(self.led, old=0.0, new=1.0)
        self.assertEqual(rid, rid2)
        self.assertEqual(len(self.led.fill_recomputations("F1")), 1)


class R3_2_ConcurrentReplayConvergence(F6Base):
    """并发竞态：唯一索引兜底后按内容收敛。"""

    def _second_ledger(self):
        led_b = Ledger(self.path)
        self.addCleanup(led_b.close)
        return led_b

    def _racy_lookup(self, led_b):
        """仅第一次查重返回未命中（模拟竞态窗口）；后续重读走真实
        路径（IntegrityError 后的内容比较必须读到真实行）。"""
        real = led_b._lookup_recompute_identity
        state = {"n": 0}

        def fake(*a, **k):
            state["n"] += 1
            if state["n"] == 1:
                return None
            return real(*a, **k)
        return mock.patch.object(
            led_b, "_lookup_recompute_identity", side_effect=fake)

    def test_concurrent_identical_replay_converges(self):
        led_a = self.led
        rid_a = self._append(led_a, old=0.0, new=1.0)
        led_b = self._second_ledger()
        # 模拟"查重后、A 提交前"的竞态窗口：B 的前置查重被固定为
        # 未命中（真实时序里该 SELECT 发生在 A commit 之前）
        with self._racy_lookup(led_b):
            rid_b = self._append(led_b, old=0.0, new=1.0)
        self.assertEqual(
            rid_b, rid_a,
            "concurrent identical replay must converge to same id")
        # 无双写
        self.assertEqual(len(self.led.fill_recomputations("F1")), 1)

    def test_concurrent_different_amounts_conflicts(self):
        rid_a = self._append(self.led, old=0.0, new=1.0)
        led_b = self._second_ledger()
        with self._racy_lookup(led_b):
            with self.assertRaises(RecomputeIdentityConflict):
                self._append(led_b, old=0.0, new=999.0)
        # A 的记录原样保留
        recs = self.led.fill_recomputations("F1")
        self.assertEqual(len(recs), 1)
        self.assertAlmostEqual(recs[0]["new_value"], 1.0)
        self.assertEqual(recs[0]["id"], rid_a)

    def test_other_integrity_errors_propagate(self):
        # 非目标索引的 IntegrityError 必须上抛（不误收敛）
        with self.assertRaises(sqlite3.IntegrityError):
            self.led.append_fill_recomputation(
                "F1", 0.0, 1.0, reason=None,  # NOT NULL 违反
                old_ctx="a", new_ctx="b", basis_ref="order:C1")


class R3_3_AtomicUpgradeBoundary(F6Base):
    """既有表升级：重复阻断 + 无半升级。"""

    def _make_legacy_table(self, duplicate: bool):
        """构造上一版本形态的 fill_recomputations（无 symbol 列/
        无唯一索引）；duplicate=True 时含同身份两条历史记录。"""
        c = self.led._conn
        c.execute(
            "CREATE TABLE IF NOT EXISTS fill_recomputations ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " fill_id TEXT NOT NULL,"
            " old_value REAL NOT NULL,"
            " new_value REAL NOT NULL,"
            " old_ctx TEXT, new_ctx TEXT,"
            " basis_ref TEXT,"
            " reason TEXT NOT NULL,"
            " recomputed_at TEXT NOT NULL)")
        rows = [("F1", 0.0, 1.0, "a", "b", "order:C1", "r1")]
        if duplicate:
            rows.append(("F1", 0.0, 2.0, "a", "b", "order:C1", "r2"))
        for r in rows:
            c.execute(
                "INSERT INTO fill_recomputations (fill_id, old_value,"
                " new_value, old_ctx, new_ctx, basis_ref, reason,"
                " recomputed_at) VALUES (?, ?, ?, ?, ?, ?, ?, 't')", r)
        c.commit()

    def _upgrade_state(self):
        c = self.led._conn
        cols = {r[1] for r in c.execute(
            "PRAGMA table_info(fill_recomputations)")}
        idx = c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index'"
            " AND name='ux_fill_recompute_ident'").fetchone()
        log = c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table'"
            " AND name='schema_upgrade_log'").fetchone()
        return ("symbol" in cols), bool(idx), bool(log)

    def test_pre_existing_duplicates_block_upgrade_atomically(self):
        self._make_legacy_table(duplicate=True)
        with self.assertRaises(SafetyViolation) as cm:
            self._append(self.led, old=0.0, new=3.0,
                         old_ctx="c", new_ctx="d")
        self.assertIn("duplicate recomputation", str(cm.exception))
        self.assertIn("F1", str(cm.exception))  # 冲突组列明
        # 无半升级：symbol 列 / 唯一索引 / 版本标记 一并缺席
        has_col, has_idx, has_log = self._upgrade_state()
        self.assertFalse(has_col, "ALTER must roll back with the block")
        self.assertFalse(has_idx)
        self.assertFalse(has_log)
        # 历史事件未被删除或合并
        self.assertEqual(len(self.led.fill_recomputations("F1")), 2)

    def test_clean_legacy_table_upgrades_atomically(self):
        self._make_legacy_table(duplicate=False)
        rid = self._append(self.led, old=0.0, new=5.0,
                           old_ctx="c", new_ctx="d")
        # 升级完整：列 + 索引 + 版本标记同在；新记录可追加
        has_col, has_idx, has_log = self._upgrade_state()
        self.assertTrue(has_col)
        self.assertTrue(has_idx)
        self.assertTrue(has_log)
        self.assertEqual(len(self.led.fill_recomputations("F1")), 2)
        # 历史行 symbol 为 NULL（保留原貌），新行带完整引用
        recs = self.led.fill_recomputations("F1")
        self.assertIsNone(recs[0]["symbol"])
        self.assertEqual(recs[1]["symbol"], None)  # 未传 symbol → NULL
        self.assertEqual(recs[1]["id"], rid)
        # 升级幂等：再次调用直接走快速路径
        self._append(self.led, old=0.0, new=6.0,
                     old_ctx="c", new_ctx="e")
        self.assertEqual(len(self.led.fill_recomputations("F1")), 3)

    def test_upgrade_log_version_marker(self):
        self._append(self.led)  # 触发升级
        row = self.led._conn.execute(
            "SELECT component, upgraded_at FROM schema_upgrade_log"
            " WHERE component='fill_recomputations_identity'").fetchone()
        self.assertIsNotNone(row)
        self.assertTrue(row["upgraded_at"])


if __name__ == "__main__":
    unittest.main()
