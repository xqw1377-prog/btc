"""FILL IDENTITY S1 验收（隔离）：迁移与历史兼容——14 个唯一合同 ID。

边界遵守：仅临时/合成/副本库；不触碰生产入口；等价性=副本/离线口径。
（提交 A：桩阶段，预期 14 项全红——失败原因为 FillMigrationStub
= 目标能力缺失，非导入错误。）
"""
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.kernel import fill_migration as fm
from aurora.kernel.ledger import Ledger

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INCIDENT = os.path.join(REPO, "state", "kernel_ledger.db")

# 旧表全列（等价核验/构造合成旧库用）
OLD_COLS = ("fill_id, client_order_id, qty, price, fee, realized_pnl,"
            " side, filled_at, synthetic, replaces_synthetic_fill_id,"
            " covered_by_fact_id, quantity_effect_applied,"
            " economic_effect_applied")


def _make_old_db(path):
    """合成旧 schema 库（orders+intents+fills），返回 Ledger 便于写入。"""
    led = Ledger(path)
    led.create_intent("I1", "BTCUSDT", "LONG", 0.25)
    led.record_order_submitting(
        client_order_id="C1", intent_id="I1", order_kind="ENTRY",
        side="BUY", position_side="LONG", quantity=0.25)
    led.insert_fill("F1", "C1", 0.25, 100.5, 0.0, "BUY", "t1")
    led.insert_fill("F2", "C1", 0.125, 100.75, 0.0, "BUY", "t2")
    return led


class S1Harness(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.old_path = os.path.join(self._tmp.name, "old.db")
        self.led = _make_old_db(self.old_path)
        self.addCleanup(self.led.close)


class T_M1_FullColumnEquivalence(S1Harness):
    def test_all_old_fields_unchanged_after_migration(self):
        before = self.led._conn.execute(
            f"SELECT {OLD_COLS} FROM fills ORDER BY fill_id").fetchall()
        fm.migrate_fills_identity(self.old_path)
        conn = fm.reopen_isolated(self.old_path)
        after = conn.execute(
            f"SELECT {OLD_COLS} FROM fills ORDER BY fill_id").fetchall()
        conn.close()
        self.assertEqual(before, after)
        # 新列在历史行上为 NULL/LEGACY（零改写、不补造 raw）
        conn = fm.reopen_isolated(self.old_path)
        rows = conn.execute(
            "SELECT origin, symbol, qty_raw, price_raw, fee_raw, fee_asset,"
            " derivation_ctx, replaced_by FROM fills").fetchall()
        conn.close()
        for r in rows:
            self.assertEqual(r[0], "LEGACY")
            self.assertEqual(r[1:], (None,) * 7)


class T_M2_IdempotentReopen(S1Harness):
    def test_second_migration_noop_and_structure_verified(self):
        fm.migrate_fills_identity(self.old_path)
        r2 = fm.migrate_fills_identity(self.old_path)
        self.assertFalse(r2.get("migrated", True))
        # 结构验证通过（重开不抛）
        conn = fm.reopen_isolated(self.old_path)
        conn.close()

    def test_marker_without_structure_refuses_open(self):
        fm.migrate_fills_identity(self.old_path)
        conn = sqlite3.connect(self.old_path)
        conn.execute("DROP INDEX ux_fills_null_symbol")
        conn.commit()
        conn.close()
        with self.assertRaises(Exception):
            fm.reopen_isolated(self.old_path)


class T_M3_IncidentCopyDrill(unittest.TestCase):
    def test_incident_replica_migration_preserves_everything(self):
        if not os.path.exists(INCIDENT):
            self.skipTest("incident ledger absent")
        with tempfile.TemporaryDirectory() as tmp:
            replica = os.path.join(tmp, "incident_copy.db")
            shutil.copyfile(INCIDENT, replica)
            orig_sha = _sha(INCIDENT)
            fills_before = _dump_fills(replica)
            kill_before = _kill(replica)
            intents_before = _intents(replica)
            fm.migrate_fills_identity(replica)
            self.assertEqual(_kill(replica), kill_before)
            self.assertEqual(_intents(replica), intents_before)
            self.assertEqual(_dump_fills(replica), fills_before)
            # 原件只读：sha 不变
            self.assertEqual(_sha(INCIDENT), orig_sha)
            # 表述口径：这是副本/离线恢复等价性


def _sha(p):
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for c in iter(lambda: fh.read(65536), b""):
            h.update(c)
    return h.hexdigest()


def _dump_fills(p):
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    rows = conn.execute(f"SELECT {OLD_COLS} FROM fills ORDER BY fill_id").fetchall()
    conn.close()
    return rows


def _kill(p):
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    v = conn.execute("SELECT engaged FROM kill_switch WHERE id=1").fetchone()[0]
    conn.close()
    return v


def _intents(p):
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    v = conn.execute(
        "SELECT intent_id, state FROM intents ORDER BY intent_id").fetchall()
    conn.close()
    return v


class T_M4_FailureRollback(S1Harness):
    def test_mid_migration_failure_rolls_back_everything(self):
        import hashlib
        pre = _sha(self.old_path)
        for fail_at in ("copy", "index", "rename"):
            with self.assertRaises(fm.MigrationError):
                fm.migrate_fills_identity(
                    self.old_path, _fail_after=fail_at)
            # 原库逐字节回滚（WAL 检查点后语义等价：行/标记/索引全无残留）
            conn = sqlite3.connect(self.old_path)
            marker = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
                " AND name='schema_meta'").fetchone()
            idx = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
                " AND name='ux_fills_null_symbol'").fetchone()
            cols = [r[1] for r in conn.execute("PRAGMA table_info(fills)")]
            conn.close()
            self.assertIsNone(marker, fail_at)
            self.assertIsNone(idx, fail_at)
            self.assertNotIn("origin", cols, fail_at)
        self.assertEqual(_sha(self.old_path), pre)

    def test_foreign_keys_pragma_restored_after_failure(self):
        conn = sqlite3.connect(self.old_path)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.close()
        with self.assertRaises(fm.MigrationError):
            fm.migrate_fills_identity(self.old_path, _fail_after="index")
        conn = sqlite3.connect(self.old_path)
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        conn.close()
        self.assertEqual(fk, 1)


class T_M5_PreCommitFKCheck(S1Harness):
    def test_dangling_fk_blocks_commit_and_rolls_back(self):
        # 走私一行悬挂 FK 的旧数据（关闭 FK 建库写入）
        conn = sqlite3.connect(self.old_path)
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            f"INSERT INTO fills ({OLD_COLS}) VALUES"
            " ('FDANG','NO-SUCH-ORDER',0.25,100.0,0,0,'BUY','t9',0,NULL,NULL,1,1)")
        conn.commit()
        conn.close()
        with self.assertRaises(fm.MigrationError):
            fm.migrate_fills_identity(self.old_path)
        conn = sqlite3.connect(self.old_path)
        idx = conn.execute(
            "SELECT name FROM sqlite_master WHERE name="
            "'ux_fills_null_symbol'").fetchone()
        conn.close()
        self.assertIsNone(idx)  # 事务内索引随回滚消失


class T_Q2_AggregationEquivalence(S1Harness):
    def test_pre_post_migration_aggregates_match(self):
        before = self.led.fills_aggregate("C1")
        fm.migrate_fills_identity(self.old_path)
        conn = fm.reopen_isolated(self.old_path)
        after = fm.aggregate_qty_v2(conn, "C1")
        conn.close()
        self.assertEqual(after["fills"], before["fills"])
        self.assertEqual(Decimal(str(before["qty"])), after["qty"])
        # 副本/离线恢复等价性（非"现网已证明"）


class T_Q3_MixedLabeling(S1Harness):
    def test_legacy_rows_labeled_and_values_untouched(self):
        fm.migrate_fills_identity(self.old_path)
        conn = fm.reopen_isolated(self.old_path)
        w = fm.FillsV2Writer(conn)
        led2 = Ledger(os.path.join(self._tmp.name, "probe.db"))
        led2.create_intent("I2", "BTCUSDT", "LONG", 0.5)
        led2.record_order_submitting(
            client_order_id="C2", intent_id="I2", order_kind="ENTRY",
            side="BUY", position_side="LONG", quantity=0.5)
        led2.close()
        # 合成旧库第二行（迁移后写 EVENT）——直接写 C1 关联不可（FK），
        # 用原生 EVENT 行验证混合标注：
        conn.execute(
            "INSERT INTO orders (client_order_id, intent_id, order_kind,"
            " side, position_side, quantity, reduce_only, state,"
            " exchange_order_id, filled_qty, avg_price, created_at,"
            " updated_at) VALUES ('CE','I1','ENTRY','BUY','LONG',0.5,0,"
            " 'FILLED',NULL,0.5,100.0,'t','t')")
        w.write_event_fill(
            fill_id="FE1", symbol="BTCUSDT", client_order_id="CE",
            qty_raw="0.5", price_raw="100.0", side="BUY", filled_at="t3")
        agg = fm.aggregate_qty_v2(conn, "C1")
        mixed = fm.aggregate_qty_v2(conn, "CE")
        conn.close()
        self.assertEqual(agg["precision"], "LEGACY_APPROXIMATE")
        self.assertEqual(mixed["precision"], "EXACT")
        # 历史数量值不变：F1/F2 的 REAL 与迁移前一致
        conn = sqlite3.connect(self.old_path)
        q = conn.execute(
            "SELECT qty FROM fills WHERE fill_id='F1'").fetchone()[0]
        conn.close()
        self.assertEqual(q, 0.25)


class T_Q4_CrossTierComparison(S1Harness):
    def test_cross_tier_is_incomplete_not_conflict(self):
        out = fm.cross_tier_compare("0.25", 0.25)
        self.assertEqual(out["result"], "COMPARISON_INCOMPLETE")
        self.assertTrue(out["restrict_new_risk"])
        self.assertFalse(out["block_reduce"])


class T_N1_NullSymbolUniqueness(S1Harness):
    def test_two_null_symbol_rows_same_trade_id_rejected(self):
        fm.migrate_fills_identity(self.old_path)
        conn = fm.reopen_isolated(self.old_path)
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO fills (fill_id, origin, client_order_id, qty,"
                " price, side, filled_at) VALUES"
                " ('F1','LEGACY','C1',0.25,100.5,'BUY','t')")
            conn.commit()
        # NULL + 非NULL 同 trade_id 共存允许
        conn.execute(
            "INSERT INTO orders (client_order_id, intent_id, order_kind,"
            " side, position_side, quantity, reduce_only, state,"
            " exchange_order_id, filled_qty, avg_price, created_at,"
            " updated_at) VALUES ('CE2','I1','ENTRY','BUY','LONG',0.1,0,"
            " 'FILLED',NULL,0.1,100.0,'t','t')")
        fm.FillsV2Writer(conn).write_event_fill(
            fill_id="F1", symbol="ETHUSDT", client_order_id="CE2",
            qty_raw="0.1", price_raw="50.0", side="BUY", filled_at="t4")
        conn.commit()
        n = conn.execute(
            "SELECT COUNT(*) FROM fills WHERE fill_id='F1'").fetchone()[0]
        conn.close()
        self.assertEqual(n, 2)


class T_DB4_TypeofChecks(S1Harness):
    def test_db_rejects_text_garbage_neg_zero_but_not_inf(self):
        fm.migrate_fills_identity(self.old_path)
        conn = fm.reopen_isolated(self.old_path)
        bad_qty = ["'garbage'", "'Infinity'", "'NaN'", -1, 0, 1e999]
        results = {}
        for i, q in enumerate(bad_qty):
            try:
                conn.execute(
                    "INSERT INTO fills (fill_id, origin, symbol,"
                    " client_order_id, qty, qty_raw, price, price_raw,"
                    " side, filled_at) VALUES (?,?,?,?,?,?,?,?, 'BUY','t')",
                    (f"X{i}", "EVENT", "BTCUSDT", "C1", q, "0.1",
                     100.0, "100.0"))
                results[repr(q)] = "accepted"
                conn.rollback()
            except sqlite3.IntegrityError:
                results[repr(q)] = "rejected"
        conn.close()
        self.assertEqual(results["'-garbage-'"] if False else results["'garbage'"], "rejected")
        self.assertEqual(results["'Infinity'"], "rejected")
        self.assertEqual(results["'NaN'"], "rejected")
        self.assertEqual(results["-1"], "rejected")
        self.assertEqual(results["0"], "rejected")
        # 分工表钉死：float inf 数据库拦不住 → 入口职责
        self.assertEqual(results["1e+999"], "accepted")


class T_DB5_OriginNoDefault(S1Harness):
    def test_missing_origin_rejected_and_event_obligations_enforced(self):
        fm.migrate_fills_identity(self.old_path)
        conn = fm.reopen_isolated(self.old_path)
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO fills (fill_id, client_order_id, qty, price,"
                " side, filled_at) VALUES ('X1','C1',0.25,100.5,'BUY','t')")
        with self.assertRaises(sqlite3.IntegrityError):  # EVENT 缺 symbol
            conn.execute(
                "INSERT INTO fills (fill_id, origin, client_order_id, qty,"
                " qty_raw, price, price_raw, side, filled_at)"
                " VALUES ('X2','EVENT','C1',0.25,'0.25',100.5,'100.5',"
                "'BUY','t')")
        with self.assertRaises(sqlite3.IntegrityError):  # EVENT 缺 raws
            conn.execute(
                "INSERT INTO fills (fill_id, origin, symbol,"
                " client_order_id, qty, price, side, filled_at)"
                " VALUES ('X3','EVENT','BTCUSDT','C1',0.25,100.5,'BUY','t')")
        conn.close()


class T_I1_CrossSymbolSameTradeID(S1Harness):
    def test_two_identities_stored_independently(self):
        fm.migrate_fills_identity(self.old_path)
        conn = fm.reopen_isolated(self.old_path)
        w = fm.FillsV2Writer(conn)
        for sym, cid in (("BTCUSDT", "CB"), ("ETHUSDT", "CE")):
            conn.execute(
                "INSERT INTO orders (client_order_id, intent_id,"
                " order_kind, side, position_side, quantity, reduce_only,"
                " state, exchange_order_id, filled_qty, avg_price,"
                " created_at, updated_at) VALUES (?,?, 'ENTRY','BUY',"
                "'LONG',0.1,0,'FILLED',NULL,0.1,100.0,'t','t')",
                (cid, "I1"))
            w.write_event_fill(
                fill_id="SAME-ID", symbol=sym, client_order_id=cid,
                qty_raw="0.1", price_raw="100.0", side="BUY", filled_at="t")
        n = conn.execute(
            "SELECT COUNT(*) FROM fills WHERE fill_id='SAME-ID'"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(n, 2)


class T_I4s_SchemaHalf(S1Harness):
    def test_schema_enforces_event_symbol_without_entry_layer(self):
        fm.migrate_fills_identity(self.old_path)
        conn = fm.reopen_isolated(self.old_path)
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO fills (fill_id, origin, client_order_id, qty,"
                " qty_raw, price, price_raw, side, filled_at)"
                " VALUES ('XE','EVENT','C1',0.25,'0.25',100.5,'100.5',"
                "'BUY','t')")
        conn.close()


class T_I7_CrossNamespaceIsolation(S1Harness):
    def test_same_identity_in_two_namespaces_mutually_invisible(self):
        paths = []
        for name in ("nsA.db", "nsB.db"):
            p = os.path.join(self._tmp.name, name)
            _make_old_db(p).close()
            fm.migrate_fills_identity(p)
            paths.append(p)
        conns = [fm.reopen_isolated(p) for p in paths]
        for i, c in enumerate(conns):
            fm.FillsV2Writer(c).write_event_fill(
                fill_id="NS-ID", symbol="BTCUSDT", client_order_id="C1",
                qty_raw="0.25", price_raw="100.0", side="BUY", filled_at="t")
            other = conns[1 - i]
            n_other = other.execute(
                "SELECT COUNT(*) FROM fills WHERE fill_id='NS-ID'"
            ).fetchone()[0]
            self.assertEqual(n_other, 0)  # 互不可见（结构性隔离）
        for c in conns:
            c.close()


if __name__ == "__main__":
    unittest.main()
