"""FILL IDENTITY S2 验收（隔离）：统一身份校验器——25 个唯一合同 ID。

按已审拆分计划映射（T-I2-6/I4e、T-D1-4、T-R1a-c/R2/R3、T-DB1-2、
T-C1-2、T-F1/F3/F3R、T-RW1、T-Q1d、T-X1-2）。
桩阶段：全部 NotImplementedError——红测试失败=能力缺失。
"""
import os
import sys
import tempfile
import threading
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.kernel import fill_identity as fi


def _row(**kw):
    base = {"symbol": "BTCUSDT", "side": "BUY", "qty": "0.25",
            "price": "100.5", "fee": "0.1", "fee_asset": "USDT"}
    base.update(kw)
    return base


class ValidatorMismatchTests(unittest.TestCase):
    """T-I3：逐字段变异矩阵（两入口一致性在 T-X1 元测试钉）。"""

    def test_field_mutation_matrix(self):
        stored = _row()
        for f, bad in (("side", "SELL"), ("qty", "0.26"),
                       ("price", "101"), ("fee", "0.2"),
                       ("fee_asset", "BNB")):
            r = fi.fill_content_mismatch(stored, _row(**{f: bad}))
            self.assertEqual(r["verdict"], "MISMATCH", f)
            self.assertIn(f, r["conflict_fields"], f)

    def test_symbol_mutation_is_mismatch(self):
        r = fi.fill_content_mismatch(_row(), _row(symbol="ETHUSDT"))
        self.assertEqual(r["verdict"], "MISMATCH")
        self.assertIn("symbol", r["conflict_fields"])


class ValidatorMatchIncompleteTests(unittest.TestCase):
    """T-I6 + 计划 §2.3：KNOWN/UNKNOWN 三态与双 UNKNOWN 不可证实。"""

    def test_full_match(self):
        r = fi.fill_content_mismatch(_row(), _row())
        self.assertEqual(r["verdict"], "MATCH")

    def test_known_vs_unknown_incomplete_either_direction(self):
        r1 = fi.fill_content_mismatch(_row(), _row(fee=None))
        r2 = fi.fill_content_mismatch(_row(fee=None), _row())
        for r in (r1, r2):
            self.assertEqual(r["verdict"], "INCOMPLETE")
            self.assertIn("fee", r["unverifiable_fields"])

    def test_double_unknown_is_incomplete_not_match(self):
        r = fi.fill_content_mismatch(_row(fee=None), _row(fee=None))
        self.assertEqual(r["verdict"], "INCOMPLETE")  # 不算"字段匹配"

    def test_null_rows_do_not_crash(self):
        r = fi.fill_content_mismatch(
            {"symbol": None, "side": None, "qty": None, "price": None,
             "fee": None, "fee_asset": None}, _row())
        self.assertEqual(r["verdict"], "INCOMPLETE")


class RawPrecisionTests(unittest.TestCase):
    """T-F3R/T-F4/T-Q1d：raw 本体校验、Decimal 数值相等、派生。"""

    def test_representation_independent_equality(self):
        r = fi.fill_content_mismatch(_row(fee="-0.400"), _row(fee="-0.4"))
        self.assertEqual(r["verdict"], "MATCH")

    def test_illegal_raws_are_unknown_not_crash(self):
        for bad in ("NaN", "Infinity", "garbage", ""):
            self.assertIsNone(fi.parse_finite(bad), bad)

    def test_support_range_cap(self):
        huge = "1." + "0" * 10001
        self.assertIsNone(fi.parse_finite(huge))


class IdentityKeyTests(unittest.TestCase):
    """T-I1/T-I4e/T-I5/T-I7：身份键语义（跨 symbol=独立身份等）。"""

    def test_cross_symbol_same_trade_id_are_distinct_identities(self):
        # 校验器按行内容比较——跨 symbol 属不同身份键，不进入本函数；
        # 身份键判定在入口层（见 EntryGateTests）；此处钉字段集不含
        # "跨 symbol 同 ID 必须冲突"的旧错误语义
        r = fi.fill_content_mismatch(_row(), _row(symbol="ETHUSDT"))
        self.assertEqual(r["verdict"], "MISMATCH")  # symbol 是事实字段


class DerivationTests(unittest.TestCase):
    """T-D1-4：推导上下文分类。"""

    def test_same_ctx_consistent(self):
        r = fi.derivation_check(
            '{"v":1}', Decimal("1.5"), Decimal("1.5"))
        self.assertFalse(r["deviation"])

    def test_same_ctx_deviation_not_identity(self):
        r = fi.derivation_check(
            '{"v":1}', Decimal("1.6"), Decimal("1.5"))
        self.assertTrue(r["deviation"])
        self.assertTrue(r["checked"])

    def test_legacy_no_ctx_not_checked(self):
        r = fi.derivation_check(None, Decimal("9"), Decimal("1"))
        self.assertFalse(r["checked"])


class RefResolutionTests(unittest.TestCase):
    """T-R1a/b/c、T-R2、T-R3：引用消解与目标存在性。"""

    def setUp(self):
        import sqlite3
        from aurora.kernel import fill_migration as fm
        from aurora.kernel.ledger import Ledger
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        p = os.path.join(self._tmp.name, "l.db")
        led = Ledger(p)
        led.create_intent("I1", "BTCUSDT", "LONG", 0.25)
        led.record_order_submitting(
            client_order_id="C1", intent_id="I1", order_kind="ENTRY",
            side="BUY", position_side="LONG", quantity=0.25)
        led.insert_fill("F1", "C1", 0.25, 100.5, 0.0, "BUY", "t1")
        led.close()
        fm.migrate_fills_identity(p)
        conn = sqlite3.connect(p)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        self.conn = conn
        self.addCleanup(conn.close)
        # 造跨 symbol 同 ID：需要第二个 symbol 的订单
        conn.execute(
            "INSERT INTO intents (intent_id, symbol, side, quantity,"
            " state, reason, created_at, updated_at)"
            " VALUES ('I2','ETHUSDT','LONG',1,'REJECTED','t','t','t')")
        conn.execute(
            "INSERT INTO orders (client_order_id, intent_id, order_kind,"
            " side, position_side, quantity, reduce_only, state,"
            " filled_qty, avg_price, created_at, updated_at)"
            " VALUES ('CE','I2','ENTRY','BUY','LONG',1,0,'FILLED',"
            "1,1,'t','t')")
        conn.execute(
            "INSERT INTO fills (fill_id, symbol, origin, client_order_id,"
            " qty, qty_raw, price, price_raw, side, filled_at)"
            " VALUES ('F1','ETHUSDT','EVENT','CE',1,'1',1,'1','BUY','t')")
        # 原 LEGACY 行 symbol=NULL；为限定引用测试补一个 BTCUSDT 限定行
        conn.execute(
            "INSERT INTO intents (intent_id, symbol, side, quantity,"
            " state, reason, created_at, updated_at)"
            " VALUES ('I3','BTCUSDT','LONG',1,'REJECTED','t','t','t')")
        conn.execute(
            "INSERT INTO orders (client_order_id, intent_id, order_kind,"
            " side, position_side, quantity, reduce_only, state,"
            " filled_qty, avg_price, created_at, updated_at)"
            " VALUES ('CB','I3','ENTRY','BUY','LONG',1,0,'FILLED',"
            "1,1,'t','t')")
        conn.execute(
            "INSERT INTO fills (fill_id, symbol, origin, client_order_id,"
            " qty, qty_raw, price, price_raw, side, filled_at)"
            " VALUES ('F2','BTCUSDT','EVENT','CB',1,'1',1,'1','BUY','t')")
        conn.commit()

    def test_qualified_ref_resolves(self):
        r = fi.resolve_fill_ref(self.conn, "BTCUSDT:F2")
        self.assertEqual(r["resolution"], "RESOLVED")
        self.assertFalse(r["audit_location_only"])

    def test_bare_id_unique_symbol_resolves(self):
        # 删掉 ETHUSDT 同 ID 行使 F1 裸 ID 在多 symbol 中唯一命中
        self.conn.execute("DELETE FROM fills WHERE symbol='ETHUSDT'")
        self.conn.commit()
        r = fi.resolve_fill_ref(self.conn, "F1")
        # F1 剩 NULL-symbol LEGACY 行 → 唯一 NULL 行也是合法"唯一命中"？
        # 设计 §1.3：唯一 NULL 行=可定位（UNRESOLVED_NULL_LEGACY）
        self.assertIn(r["resolution"],
                      ("RESOLVED", "UNRESOLVED_NULL_LEGACY"))
        r2 = fi.resolve_fill_ref(self.conn, "F2")
        self.assertEqual(r2["resolution"], "RESOLVED")

    def test_bare_id_multi_symbol_ambiguous(self):
        r = fi.resolve_fill_ref(self.conn, "F1")
        self.assertEqual(r["resolution"], "UNRESOLVED_AMBIGUOUS")
        self.assertTrue(r["audit_location_only"])

    def test_null_legacy_location_is_not_identity(self):
        # T-R2：F1 是迁移产生的 LEGACY 行（symbol=NULL，CHECK 拒绝
        # EVENT 行置 NULL——S1 schema 本身在保护此语义）
        self.conn.execute("DELETE FROM fills WHERE symbol='ETHUSDT'")
        self.conn.commit()
        r = fi.resolve_fill_ref(self.conn, "F1")
        self.assertEqual(r["resolution"], "UNRESOLVED_NULL_LEGACY")
        self.assertTrue(r["audit_location_only"])

    def test_new_ref_validation_rejects_bare_and_dangling(self):
        self.assertFalse(fi.validate_new_ref(self.conn, "F1")["ok"])
        self.assertFalse(
            fi.validate_new_ref(self.conn, "BTCUSDT:NOPE")["ok"])
        self.assertTrue(
            fi.validate_new_ref(self.conn, "BTCUSDT:F2")["ok"])

    def test_attribution_anomaly(self):
        r = fi.check_attribution(self.conn, "ETHUSDT", "C1")
        self.assertEqual(r["verdict"], "ATTRIBUTION_ANOMALY")
        r2 = fi.check_attribution(self.conn, "BTCUSDT", "C1")
        self.assertEqual(r2["verdict"], "OK")
        r3 = fi.check_attribution(self.conn, "BTCUSDT", "NOPE")
        self.assertEqual(r3["verdict"], "ORDER_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
