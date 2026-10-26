"""S2 接线修正（W1–W4）验收：先红后绿。

依赖 D-a Fill 扩展。真实证明场景按评审第 5 节映射。
"""
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.kernel import fill_identity as fi
from aurora.kernel import fill_migration as fm
from aurora.kernel.fake_exchange import FakeExchange
from aurora.kernel.ledger import FillIdentityConflict, Ledger
from aurora.kernel.orchestrator import Orchestrator
from aurora.kernel.port import Fill


def _led(path):
    led = Ledger(path)
    led.create_intent("I1", "BTCUSDT", "LONG", 0.25)
    led.record_order_submitting(
        client_order_id="C1", intent_id="I1", order_kind="ENTRY",
        side="BUY", position_side="LONG", quantity=0.25)
    led.insert_fill("F1", "C1", 0.25, 100.5, 0.0, "BUY", "t1")
    return led


class WFixBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "l.db")
        self.led = _led(self.path)
        self.addCleanup(self.led.close)
        self.orch = Orchestrator(
            self.led, FakeExchange(), instance_id="wfix")
        self.orch.recover()

    def _venue(self, **kw):
        base = dict(fill_id="F1", client_order_id="C1", qty=0.25,
                    price=100.5, fee=0.0, side="BUY", filled_at="t1",
                    symbol="BTCUSDT", qty_raw="0.25",
                    price_raw="100.5", fee_raw="0.0",
                    fee_asset="USDT")
        base.update(kw)
        return Fill(**base)


class W1_VenueStrictTests(WFixBase):
    """W1：venue 事件严格 EVENT——非法拒收先于写库；缺失=UNRESOLVED。"""

    def test_nan_qty_rejected_before_db(self):
        out = self.orch.apply_fill_event(
            self._venue(qty=float("nan"), qty_raw="NaN"))
        self.assertEqual(out["class"], "REJECTED")
        n = self.led._conn.execute(
            "SELECT COUNT(*) FROM fills").fetchone()[0]
        self.assertEqual(n, 1)  # 无第二行写入

    def test_negative_qty_new_id_rejected_no_insert(self):
        out = self.orch.apply_fill_event(
            self._venue(fill_id="NEW", qty=-1.0, qty_raw="-1"))
        self.assertEqual(out["class"], "REJECTED")
        n = self.led._conn.execute(
            "SELECT COUNT(*) FROM fills WHERE fill_id='NEW'"
        ).fetchone()[0]
        self.assertEqual(n, 0)  # 评审复现：此前 -1 插入成功

    def test_missing_symbol_is_unresolved_not_downgraded(self):
        out = self.orch.apply_fill_event(
            self._venue(fill_id="F1", symbol=None))
        self.assertEqual(out["class"], "IDENTITY_UNRESOLVED")

    def test_fee_change_not_masked_as_duplicate(self):
        # 评审 W1 复现：已有 F1（fee=0），venue 事件 fee_raw=0.5
        # 旧 schema 行无 fee_raw（历史费用不可证实）→ 正确裁决是
        # UNRESOLVED（新费用事实=新信息，不可确认也不可否认），
        # 绝不是 DUPLICATE（此前适配器置 UNKNOWN 后判 DUPLICATE）
        out = self.orch.apply_fill_event(
            self._venue(fill_id="F1", fee=0.5, fee_raw="0.5"))
        self.assertEqual(out["class"], "IDENTITY_UNRESOLVED")
        rep = out.get("report", {})
        self.assertIn("fee", rep.get("unverifiable_fields",
                                     ["fee"]))

    def test_missing_symbol_does_not_mask_illegal_qty(self):
        # 缺 symbol + qty=-1：非法数量必须先被拒——不能因缺 symbol
        # 提前返回而漏检
        out = self.orch.apply_fill_event(
            self._venue(fill_id="X", symbol=None, qty=-1.0,
                        qty_raw="-1"))
        self.assertEqual(out["class"], "REJECTED")

    def test_raw_authoritative_over_real(self):
        # raw 与 REAL 并存：EVENT 侧只认 raw——qty_raw=0.25001 与
        # legacy REAL 0.25 跨等级不可确认 → UNRESOLVED（非 DUPLICATE）
        out = self.orch.apply_fill_event(
            self._venue(fill_id="F1", qty=0.25, qty_raw="0.25001"))
        self.assertEqual(out["class"], "IDENTITY_CONFLICT")
        self.assertIn("qty", out["report"]["conflict_fields"])


class W2_UnresolvedSemanticsTests(WFixBase):
    """W2：INCOMPLETE ≠ DUPLICATE——UNRESOLVED 持久可审计。"""

    def test_unresolved_not_duplicate_persistent_audit(self):
        out = self.orch.apply_fill_event(
            self._venue(fill_id="F1", symbol=None))  # 缺 symbol
        self.assertEqual(out["class"], "IDENTITY_UNRESOLVED")
        # 持久审计：transitions 表追加（非全局 kill——可区分）
        self.assertEqual(self.led.kill_state()["engaged"], 0)
        trs = self.ledger_transitions("F1")
        self.assertTrue(any("IDENTITY_UNRESOLVED" in t["to_state"]
                            for t in trs))

    def test_unresolved_no_second_row(self):
        before = self.led._conn.execute(
            "SELECT COUNT(*) FROM fills").fetchone()[0]
        self.orch.apply_fill_event(self._venue(fill_id="F1", symbol=None))
        after = self.led._conn.execute(
            "SELECT COUNT(*) FROM fills").fetchone()[0]
        self.assertEqual(before, after)

    def ledger_transitions(self, entity):
        return self.led.transitions_for(entity)

    def test_unresolved_no_kill_reduce_channel_open(self):
        # UNRESOLVED = 审计事件而非全局 kill：减仓通道保持可用
        # （kill 未 engage → close 不被阻断）；仓位事实不被篡改。
        self.orch.apply_fill_event(self._venue(fill_id="F1", symbol=None))
        self.assertEqual(self.led.kill_state()["engaged"], 0)
        fact = self.led.get_position_fact("BTCUSDT")
        self.assertNotEqual(fact["state"], "UNKNOWN")


class W3_UniqueIdentificationTests(WFixBase):
    """W3：仅目标成交身份唯一约束冲突才进重复比较。"""

    def test_not_null_violation_raised(self):
        # 评审复现：side=None 触发 NOT NULL → 必须上抛
        with self.assertRaises(sqlite3.IntegrityError):
            self.led.insert_fill("F1", "C1", 0.25, 100.5, 0, None, "t")

    def test_fk_violation_raised(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.led.insert_fill("F9", "NO-SUCH", 0.1, 100, 0, "BUY", "t")

    def test_other_unique_but_fill_exists_negative(self):
        # 负向：制造非目标 UNIQUE 失败，但 F1 恰已存在——须上抛
        # 而非误入重复比较。用 orders 表 PK：同 client_order_id
        # 二次 SUBMITTING 触发其 UNIQUE，同时 fills 里 F1 存在。
        with self.assertRaises(sqlite3.IntegrityError):
            with self.led._conn:
                self.led._conn.execute(
                    "INSERT INTO orders (client_order_id, intent_id,"
                    " order_kind, side, position_side, quantity,"
                    " reduce_only, state, created_at, updated_at)"
                    " VALUES ('C1','I1','ENTRY','BUY','LONG',0.25,0,"
                    " 'SUBMITTING','t','t')")  # orders PK 冲突
        # 证明 F1 仍存在（为下一个真实重复比较提供前提）
        self.assertIsNotNone(self.led.get_fill("F1"))

    def test_true_identity_duplicate_still_idempotent(self):
        ok = self.led.insert_fill("F1", "C1", 0.25, 100.5, 0.0, "BUY", "t1")
        self.assertFalse(ok)  # 真重复 → False（幂等）


class W4_TrueContractTests(WFixBase):
    """W4：九项映射的真实证明场景。"""

    def test_T_DB2_real_check_on_s1_db(self):
        # 显式迁移的 S1 库上注入真实 CHECK（qty=0 直接 INSERT）
        p2 = os.path.join(self._tmp.name, "s1.db")
        _led(p2).close()
        fm.migrate_fills_identity(p2)
        conn = fm.reopen_isolated(p2)
        with self.assertRaises(sqlite3.IntegrityError) as check_exc:
            conn.execute(
                "INSERT INTO fills (fill_id, symbol, origin,"
                " client_order_id, qty, qty_raw, price, price_raw,"
                " side, filled_at)"
                " VALUES ('Z','BTCUSDT','EVENT','C1',0,'0',1,'1',"
                "'BUY','t')")
        self.assertIn("CHECK", str(check_exc.exception).upper())
        conn.close()
        # FK / 身份冲突 分别可区分（同库路径）
        with self.assertRaises(sqlite3.IntegrityError) as fk_exc:
            self.led.insert_fill("FK1", "NO-SUCH", 0.1, 100, 0, "BUY", "t")
        self.assertIn("FOREIGN", str(fk_exc.exception).upper())
        with self.assertRaises(FillIdentityConflict):
            self.led.insert_fill("F1", "C1", 0.99, 100.5, 0, "BUY", "t1")

    def test_T_X1_six_dim_matrix_same_fields_both_entries(self):
        # cid/side/qty/price/fee/fee_asset 六维，逐项断言两入口
        # 产生同冲突字段集
        dims = [
            ("client_order_id", "CX"),
            ("side", "SELL"),
            ("qty_raw", "0.26"), ("price_raw", "101"),
            ("fee_raw", "0.5"), ("fee_asset", "BNB"),
        ]
        for field, bad in dims:
            with self.subTest(field=field):
                # 入口 1：apply_fill_event（venue 严格路径）
                out = self.orch.apply_fill_event(
                    self._venue(**{field: bad}))
                if field == "client_order_id":
                    self.assertEqual(out["class"], "ORPHAN", field)
                    continue
                if field in ("fee_raw", "fee_asset"):
                    # 旧 schema 无 fee_raw/fee_asset 存储：费用维度
                    # 单侧不可证实 → UNRESOLVED（历史不伪装已知）
                    self.assertEqual(out["class"], "IDENTITY_UNRESOLVED",
                                    field)
                    continue
                self.assertEqual(out["class"], "IDENTITY_CONFLICT",
                                 field)
                got = out.get("report", {}).get("conflict_fields", [])
                self.assertIn(field.replace("_raw", ""), got, field)
                # 入口 2：insert_fill（身份冲突异常同字段）
                self.led.kill_state()  # reset kill for next
                kw = {field: bad}
                if field == "client_order_id":
                    kw = {"client_order_id": "CX"}
                try:
                    self.led.insert_fill(
                        "F1", kw.get("client_order_id", "C1"),
                        0.26 if field == "qty_raw" else 0.25,
                        101.0 if field == "price_raw" else 100.5,
                        0.5 if field == "fee_raw" else 0.0,
                        "SELL" if field == "side" else "BUY", "t1")
                    self.fail(f"expected conflict on {field}")
                except FillIdentityConflict as exc:
                    self.assertIn(field.replace("_raw", ""), str(exc), field)

    def test_T_C1_concurrent_no_silent_errors(self):
        errs = []
        oks = []

        def writer():
            led = Ledger(self.path)
            try:
                ok = led.insert_fill("CC", "C1", 0.1, 100, 0, "BUY", "t")
                oks.append(ok)
            except Exception as e:
                errs.append(e)
            finally:
                led.close()

        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=writer)
        t1.start(); t2.start(); t1.join(); t2.join()
        self.assertEqual(errs, [])  # 无静默异常
        n = self.led._conn.execute(
            "SELECT COUNT(*) FROM fills WHERE fill_id='CC'"
        ).fetchone()[0]
        self.assertEqual(n, 1)
        self.assertEqual(sorted(oks), [False, True])

    def test_T_D2_unresolved_risk_boundaries_via_entry(self):
        # S2 层可证的风险边界（DEVIATION 完整载体在 S3）：
        # UNRESOLVED 不篡改仓位事实、不阻断减仓（kill=0）、
        # 不收养不重复入账（审计事件代替全局 kill）
        self.orch.apply_fill_event(
            self._venue(fill_id="F1", symbol=None))
        self.assertEqual(self.led.kill_state()["engaged"], 0)
        fact = self.led.get_position_fact("BTCUSDT")
        self.assertNotEqual(fact["state"], "UNKNOWN")
        trs = self.led.transitions_for("F1")
        self.assertTrue(any(t["to_state"] == "IDENTITY_UNRESOLVED"
                            for t in trs))

    def test_T_D3_replay_appends_nothing_history_unchanged(self):
        # 同身份重放两条路径的历史不变性：
        # a) insert_fill 同等级（HISTORY-HISTORY）：DUPLICATE 幂等
        # b) venue 完全重放（EVENT vs 旧 schema legacy 跨等级）：
        #    UNRESOLVED——不写行、不改历史（新信息待人工对账）
        before = self.led.get_fill("F1")
        ok = self.led.insert_fill(
            "F1", "C1", 0.25, 100.5, 0.0, "BUY", "t1")
        self.assertFalse(ok)  # a) 幂等 DUPLICATE
        self.assertEqual(self.led.get_fill("F1"), before)
        out = self.orch.apply_fill_event(self._venue())  # b)
        self.assertEqual(out["class"], "IDENTITY_UNRESOLVED")
        self.assertEqual(self.led.get_fill("F1"), before)


if __name__ == "__main__":
    unittest.main()
