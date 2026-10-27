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
from aurora.kernel.fake_exchange import FakeExchange
from aurora.kernel.ledger import Ledger
from aurora.kernel.orchestrator import Orchestrator
import sqlite3
import threading
from aurora.kernel.fill_migration import cross_tier_compare


def _row(**kw):
    base = {"origin": "EVENT", "client_order_id": "C1",
            "symbol": "BTCUSDT", "side": "BUY",
            "qty": "0.25", "qty_raw": "0.25",
            "price": "100.5", "price_raw": "100.5",
            "fee": "0.1", "fee_raw": "0.1", "fee_asset": "USDT"}
    base.update(kw)
    return base


class ValidatorMismatchTests(unittest.TestCase):
    """T-I3：逐字段变异矩阵（两入口一致性在 T-X1 元测试钉）。"""

    def test_field_mutation_matrix(self):
        stored = _row()
        for f, bad in (("side", "SELL"), ("qty_raw", "0.26"),
                       ("price_raw", "101"), ("fee_raw", "0.2"),
                       ("fee_asset", "BNB"), ("client_order_id", "CX")):
            r = fi.fill_content_mismatch(stored, _row(**{f: bad}))
            self.assertEqual(r["verdict"], "MISMATCH", f)
            self.assertIn(f.replace("_raw", ""),
                          r["conflict_fields"], f)

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
        r1 = fi.fill_content_mismatch(_row(), _row(fee_raw=None))
        r2 = fi.fill_content_mismatch(_row(fee_raw=None), _row())
        for r in (r1, r2):
            self.assertEqual(r["verdict"], "INCOMPLETE")
            self.assertIn("fee", r["unverifiable_fields"])

    def test_double_unknown_is_incomplete_not_match(self):
        r = fi.fill_content_mismatch(_row(fee_raw=None), _row(fee_raw=None))
        self.assertEqual(r["verdict"], "INCOMPLETE")  # 不算"字段匹配"

    def test_null_rows_rejected_or_incomplete(self):
        # 来源边界：无 origin 的载荷 → ValueError（评审复现的封死）；
        # 可信历史行全 NULL → INCOMPLETE
        with self.assertRaises(ValueError):
            fi.fill_content_mismatch(
                {"symbol": None, "side": None, "qty": None,
                 "price": None, "fee": None, "fee_asset": None}, _row())
        legacy = fi.legacy_row(
            client_order_id="C1", symbol=None, side=None,
            qty=None, price=None)
        r = fi.compare_as("HISTORY", legacy, dict(legacy))
        self.assertEqual(r["verdict"], "INCOMPLETE")


class RawPrecisionTests(unittest.TestCase):
    """T-F3R/T-F4/T-Q1d：raw 本体校验、Decimal 数值相等、派生。"""

    def test_representation_independent_equality(self):
        r = fi.fill_content_mismatch(_row(fee_raw="-0.400"), _row(fee_raw="-0.4"))
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
            '{"v":1}', '{"v":1}', Decimal("1.5"), Decimal("1.5"))
        self.assertFalse(r["deviation"])

    def test_same_ctx_deviation_not_identity(self):
        r = fi.derivation_check(
            '{"v":1}', '{"v":1}', Decimal("1.6"), Decimal("1.5"))
        self.assertTrue(r["deviation"])
        self.assertTrue(r["checked"])

    def test_legacy_no_ctx_not_checked(self):
        r = fi.derivation_check(None, None, Decimal("9"), Decimal("1"))
        self.assertFalse(r["checked"])
        self.assertEqual(r["path"], "NO_CTX")


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


class S2ReviewRepros(unittest.TestCase):
    """评审四项阻断 + 非法数量复现（红）。"""

    def test_S2_01_cid_is_identity_fact(self):
        stored = _row(client_order_id="A")
        incoming = _row(client_order_id="B")
        r = fi.fill_content_mismatch(stored, incoming)
        self.assertEqual(r["verdict"], "MISMATCH")
        self.assertIn("client_order_id", r["conflict_fields"])

    def test_S2_02_nonnumeric_double_unknown_is_incomplete(self):
        for f in ("symbol", "side", "fee_asset"):
            r = fi.fill_content_mismatch(
                _row(**{f: None}), _row(**{f: None}))
            self.assertEqual(r["verdict"], "INCOMPLETE", f)
            self.assertIn(f, r["unverifiable_fields"], f)

    def test_S2_03_event_reads_raw_not_real_and_detects_diff(self):
        r = fi.fill_content_mismatch(
            _row(origin="EVENT", qty_raw="1.00000000000000000001",
                 qty="1.0"),
            _row(origin="EVENT", qty_raw="1.00000000000000000002",
                 qty="1.0"))
        self.assertEqual(r["verdict"], "MISMATCH")

    def test_S2_03_cross_tier_cannot_confirm_match(self):
        legacy = fi.legacy_row(
            client_order_id="C1", symbol="BTCUSDT", side="BUY",
            qty=0.25, price=100.5)
        # 跨等级=EVENT 模式行 vs HISTORY 模式行——由调用侧分别声明
        ev = _row(origin="EVENT")
        r_ev = fi.compare_as("EVENT", ev, ev)
        r_hist = fi.compare_as("HISTORY", legacy, legacy)
        # 等级差异的判定入口：cross_tier_compare（S1 合同）
        r = cross_tier_compare(ev.get("qty_raw"), legacy["qty"])
        self.assertEqual(r["result"], "COMPARISON_INCOMPLETE")
        self.assertTrue(r["restrict_new_risk"])
        self.assertFalse(r["block_reduce"])

    def test_S2_03_negative_qty_is_invalid_not_matchable(self):
        with self.assertRaises(ValueError):
            fi.fill_content_mismatch(
                _row(origin="EVENT", qty_raw="-1"),
                _row(origin="EVENT", qty_raw="-1"))

    def test_S2_04_derivation_ctx_comparison(self):
        # 同 ctx 不一致 → DEVIATION
        r = fi.derivation_check(
            '{"v":1}', '{"v":1}', Decimal("1.6"), Decimal("1.5"))
        self.assertTrue(r["deviation"])
        # 不同 ctx → 显式重算路径，不判 DEVIATION
        r2 = fi.derivation_check(
            '{"v":1}', '{"v":2}', Decimal("9.9"), Decimal("1.5"))
        self.assertFalse(r2["deviation"])
        self.assertEqual(r2["path"], "EXPLICIT_RECOMPUTE")


class S2_03_ResidualRepros(unittest.TestCase):
    """评审三项残留复现（红）。"""

    def test_legacy_fee_float_not_in_comparison(self):
        # 真实迁移形态：LEGACY 行 fee_raw=NULL，仅展示列 fee 变化
        a = {"origin": "LEGACY", "client_order_id": "C1",
             "symbol": None, "side": "BUY", "qty": 0.25,
             "price": 100.5, "fee": 0.0, "fee_asset": None}
        b = dict(a, fee=0.5)
        r = fi.compare_as("HISTORY", a, b)
        self.assertEqual(r["verdict"], "INCOMPLETE")  # fee 不可证实
        self.assertNotEqual(r["verdict"], "MISMATCH")

    def test_cross_tier_does_not_mask_known_cid_conflict(self):
        legacy = fi.legacy_row(
            client_order_id="A", symbol=None, side="BUY",
            qty=0.25, price=100.5)
        event = _row(origin="EVENT", client_order_id="B")
        # 跨等级下已知 cid 冲突不被掩盖：compare_as 混模式禁止，
        # 该语义由入口层分别归一化后比较离散字段——此处直接验证
        # 入口层等价逻辑（v5 辅助）
        r = fi.compare_mixed(legacy, event)
        self.assertEqual(r["verdict"], "MISMATCH")
        self.assertIn("client_order_id", r["conflict_fields"])

    def test_unknown_origin_rejected(self):
        row = {"origin": "TYPO", "client_order_id": "C1",
               "symbol": "BTCUSDT", "side": "BUY", "qty": 0.25,
               "price": 100.5, "fee": None, "fee_asset": None}
        with self.assertRaises(ValueError):
            fi.fill_content_mismatch(row, dict(row))


class S2_OriginSourceBoundaryTests(unittest.TestCase):
    """评审残留复现：省略/伪造 origin 不得绕过 EVENT raw 校验。"""

    ROW = {"client_order_id": "A", "symbol": "BTCUSDT", "side": "BUY",
           "qty": 1.0, "qty_raw": "-1",
           "price": 100.0, "price_raw": "100",
           "fee_raw": "0.1", "fee_asset": "USDT"}

    def test_omitted_origin_cannot_bypass_raw_validation(self):
        with self.assertRaises(ValueError):
            fi.fill_content_mismatch(dict(self.ROW), dict(self.ROW))

    def test_empty_origin_cannot_bypass(self):
        row = dict(self.ROW, origin="")
        with self.assertRaises(ValueError):
            fi.fill_content_mismatch(row, dict(row))

    def test_self_declared_legacy_on_new_payload_rejected(self):
        # 载荷自填 LEGACY 降级 → 拒（有 raw 字段说明是新事件形态）
        row = dict(self.ROW, origin="LEGACY")
        with self.assertRaises(ValueError):
            fi.fill_content_mismatch(row, dict(row))

    def test_trusted_legacy_path_still_works(self):
        # 可信历史模式：legacy_row 构造 → 接受；数值近似同值匹配；
        # fee 无 fee_raw → 不可证实 → INCOMPLETE（合同 §3.4）
        row = fi.legacy_row(
            client_order_id="A", symbol=None, side="BUY",
            qty=1.0, price=100.0)
        r = fi.compare_as("HISTORY", row, dict(row))
        self.assertIn(r["verdict"], ("MATCH", "INCOMPLETE"))
        self.assertNotEqual(r["verdict"], "MISMATCH")
        self.assertNotIn("qty", r.get("unverifiable_fields", []))

    def test_trusted_legacy_qty_channel_sensitivity(self):
        # 真实历史行数值通道可用：qty 变化 → MISMATCH（数值仍参与）
        a = fi.legacy_row(client_order_id="A", symbol=None,
                          side="BUY", qty=0.25, price=100.5)
        b = fi.legacy_row(client_order_id="A", symbol=None,
                          side="BUY", qty=0.26, price=100.5)
        r = fi.compare_as("HISTORY", a, b)
        self.assertEqual(r["verdict"], "MISMATCH")
        self.assertIn("qty", r["conflict_fields"])


class S2_TrustedSourceModeTests(unittest.TestCase):
    """评审残留：载荷不能自选信任等级——模式由调用路径显式决定。"""

    FORGED = {"origin": "LEGACY", "client_order_id": "A",
              "symbol": "BTCUSDT", "side": "BUY",
              "qty": -1.0, "price": 100.0,
              "fee": None, "fee_asset": "USDT"}

    def test_forged_legacy_without_raws_rejected(self):
        with self.assertRaises(ValueError):
            fi.compare_as("EVENT", self.FORGED, self.FORGED)

    def test_event_mode_ignores_payload_origin(self):
        # 新事件入口固定 EVENT 模式：载荷自填 LEGACY 也按 EVENT 校验
        # → 缺 raw → 拒收
        with self.assertRaises(ValueError):
            fi.compare_as("EVENT", self.FORGED, self.FORGED)

    def test_history_mode_explicit_only(self):
        # 历史模式只能显式启用：trusted=True 参数，不读载荷 origin
        row = dict(self.FORGED, origin="EVENT")  # 载荷 origin 被忽略
        r = fi.compare_as("HISTORY", row, row)
        self.assertIn(r["verdict"], ("MATCH", "INCOMPLETE"))

    def test_default_call_rejects_legacy_payload(self):
        # 无模式参数的裸调用：载荷形 LEGACY 且无 raw → 拒（不能自选）
        with self.assertRaises(ValueError):
            fi.fill_content_mismatch(self.FORGED, self.FORGED)

    def test_real_history_recovery_unchanged(self):
        # 真实历史恢复（显式 HISTORY）：qty 通道可用、同值不冲突
        a = {"client_order_id": "A", "symbol": None, "side": "BUY",
             "qty": 0.25, "price": 100.5}
        b = {"client_order_id": "A", "symbol": None, "side": "BUY",
             "qty": 0.26, "price": 100.5}
        r1 = fi.compare_as("HISTORY", a, a)
        r2 = fi.compare_as("HISTORY", a, b)
        self.assertNotEqual(r1["verdict"], "MISMATCH")
        self.assertEqual(r2["verdict"], "MISMATCH")
        self.assertIn("qty", r2["conflict_fields"])


class S2_EntryWiringTests(unittest.TestCase):
    """两入口接线九项合同（T-DB1/2、T-C1/2、T-X1/2、T-I4e、T-I5、T-D3）。"""

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
        self.orch = Orchestrator(led, FakeExchange(), instance_id="w")
        self.orch.recover()

    def _event(self, **kw):
        from aurora.kernel.port import Fill as F
        # D-a 夹具补字段：venue 事件要求 symbol/raw 齐备
        base = dict(fill_id="F1", client_order_id="C1", qty=0.25,
                    price=100.5, fee=0.0, side="BUY", filled_at="t1",
                    symbol="BTCUSDT", qty_raw="0.25",
                    price_raw="100.5", fee_raw="0.0",
                    fee_asset="USDT")
        base.update(kw)
        return F(**base)

    def test_T_DB1_fk_violation_not_swallowed(self):
        with self.assertRaises(Exception) as hc:
            self.led.insert_fill(
                "F2", "NO-SUCH-ORDER", 0.1, 100, 0, "BUY", "t")
        self.assertNotIsInstance(hc.exception, type(None))
        # 不得返回 False（吞成 DUPLICATE）
        # insert_fill 现在要么抛 FK 异常要么成功——验证它抛
        self.assertNotEqual(type(hc.exception).__name__, "bool")

    def test_T_DB2_fk_and_check_distinguishable(self):
        from aurora.kernel.ledger import FillIdentityConflict
        # FK：引用不存在订单 → sqlite3.IntegrityError (FOREIGN KEY)
        with self.assertRaises(sqlite3.IntegrityError) as fk_exc:
            self.led.insert_fill(
                "F3", "NO-SUCH", 0.1, 100, 0, "BUY", "t")
        self.assertIn("FOREIGN", str(fk_exc.exception).upper())
        # CHECK：同 fill_id 不同内容 → FillIdentityConflict（可区分类）
        try:
            self.led.insert_fill(
                "F1", "C1", 0.99, 100.5, 0, "BUY", "t1")  # qty 变异
            conflict_raised = False
        except FillIdentityConflict:
            conflict_raised = True
        self.assertTrue(conflict_raised)

    def test_T_C1_concurrent_same_identity_exactly_once(self):
        results = []
        errs = []

        def writer():
            led = Ledger(self.path)  # 独立连接（WAL + busy_timeout）
            try:
                ok = led.insert_fill("CC1", "C1", 0.1, 100, 0, "BUY", "t")
                results.append(ok)
            except Exception as e:
                errs.append(e)
            finally:
                led.close()

        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=writer)
        t1.start(); t2.start(); t1.join(); t2.join()
        n = self.led._conn.execute(
            "SELECT COUNT(*) FROM fills WHERE fill_id='CC1'"
        ).fetchone()[0]
        self.assertEqual(n, 1)  # 恰好一条

    def test_T_C2_concurrent_conflict_not_lost(self):
        from aurora.kernel.ledger import FillIdentityConflict
        errs = []

        def writer(qty):
            led = Ledger(self.path)
            try:
                led.insert_fill("CC2", "C1", qty, 100, 0, "BUY", "t")
            except FillIdentityConflict as e:
                errs.append(e)
            except sqlite3.IntegrityError:
                errs.append("unique-race")
            finally:
                led.close()

        t1 = threading.Thread(target=writer, args=(0.1,))
        t2 = threading.Thread(target=writer, args=(0.2,))
        t1.start(); t2.start(); t1.join(); t2.join()
        self.assertTrue(len(errs) >= 1)  # 冲突可见，无静默丢失

    def test_T_X1_two_entry_boundary_proved(self):
        # 两入口精度边界（冻结语义）：insert_fill（同等级 HISTORY）
        # 检出 qty 冲突 → FillIdentityConflict；venue 入口（跨等级）
        # → UNRESOLVED——同一校验器、不同模式、各自正确
        from aurora.kernel.ledger import FillIdentityConflict
        with self.assertRaises(FillIdentityConflict) as ledger_exc:
            self.led.insert_fill(
                "F1", "C1", 0.99, 100.5, 0, "BUY", "t1")
        self.assertIn("qty", str(ledger_exc.exception))
        out = self.orch.apply_fill_event(
            self._event(qty=0.99, qty_raw="0.99"))
        self.assertEqual(out["class"], "IDENTITY_UNRESOLVED")

    def test_T_X2_legacy_w43_tests_unchanged(self):
        # 既有 W43 冲突测试不改断言全绿（EventEntryConflictBypassTests
        # 在本套件运行）；此处钉同一冲突在两入口的一致签名：
        # class=IDENTITY_CONFLICT + kill engaged + 不写新行
        # 离散事实（side）冲突在两入口都能检出（冻结语义保留）
        out = self.orch.apply_fill_event(
            self._event(side="SELL"))
        self.assertEqual(out["class"], "IDENTITY_CONFLICT")
        self.assertTrue(out.get("kill_engaged"))
        self.assertEqual(self.led.kill_state()["engaged"], 1)

    def test_T_I4e_missing_symbol_unresolved(self):
        # 缺 symbol → UNRESOLVED（不凭空补、不降级、不确认重复）
        out = self.orch.apply_fill_event(
            self._event(fill_id="F1", symbol=None))
        self.assertEqual(out["class"], "IDENTITY_UNRESOLVED")

    def test_T_I5_identity_unresolved_not_adopted(self):
        # 同 fill_id 不同内容 → IDENTITY_CONFLICT（不收养为重复），
        # kill 熔断——已在 T_X1/T_X2 钉；此处验证不产生第二条 fills
        before = self.led._conn.execute(
            "SELECT COUNT(*) FROM fills").fetchone()[0]
        self.orch.apply_fill_event(
            self._event(qty=0.99, qty_raw="0.99"))
        after = self.led._conn.execute(
            "SELECT COUNT(*) FROM fills").fetchone()[0]
        self.assertEqual(before, after)  # 未收养、未重复入账

    def test_T_D3_explicit_recompute_does_not_overwrite(self):
        # 推导重算走显式事件——本项在 S3 费用投影落地；入口层
        # 仅验证 derivation_check 分类可用
        r = fi.derivation_check(
            '{"v":1}', '{"v":2}', Decimal("9"), Decimal("1"))
        self.assertEqual(r["path"], "EXPLICIT_RECOMPUTE")
        self.assertFalse(r["deviation"])
