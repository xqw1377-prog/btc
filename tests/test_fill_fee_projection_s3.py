"""FILL IDENTITY S3：费用补充与投影（离线隔离实现）——14 项测试。

开工令（2026-10-28，基线 8511151）：仅限离线隔离实现。
- 记账效果 = 离线效果记录（fee_effect_ledger），不写账户余额/
  PnL/风险预算；不接任何消费方。
- 冲突只隔离告警（CONFLICTED）；仅带凭据的显式修正产生新版本；
  同资产 delta、跨资产撤销旧+应用新必须原子。
- FIX7 事务纪律：写入入口遇调用方未提交事务，写入前拒绝。

T-ID 映射：
  T-F2e  入口声明语义（KNOWN 才强制 raw+asset；UNKNOWN 合法）
  T-F4   Decimal 数值相等（-0.400≡-0.4；0.40≠0.4+1e-300）
  T-F4R  历史 float 不参与比较（基线 UNKNOWN；无伪差冲突）
  T-FP1  UNKNOWN+单补充→v1 全额恰一次；同稳定 ID 重放零新增
  T-FP2  双 UNKNOWN→INCOMPLETE：不投影、不写 0、不判重复
  T-FP3  KNOWN 基线+冲突补充→FEE_CONFLICT：原值保留
  T-FP4  补充到达不触发重算；仅显式修正产生 delta（绝不二次全额）
  T-FP5  effect_key 幂等：重放被 UNIQUE 拒；旧版本键不可复活
  T-FP6  三步单事务：c 步失败→a 步补充回滚（+调用方事务拒绝）
  T-FP7  一致补充→零经济影响（无新版本）
  T-FP8  冲突→CONFLICTED：隔离+告警，零自动差额；仅修正放行
  T-FP9  跨资产修正→按资产双蹄同事务；一蹄证据不足两蹄都不应用
  T-F6a  长尾无损（30+ 位；对照默认 prec28 丢尾）
  T-F6b  输入边界：|adjusted|>999999/非有限入口拒收；扩精度仍
         Inexact → 拒绝入账
"""
import os
import sqlite3
import sys
import tempfile
import unittest
from decimal import Decimal, localcontext
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.kernel import fill_migration as fm
from aurora.kernel.ledger import Ledger
from aurora.p0_boundary import SafetyViolation

import aurora.kernel.fee_projection as fp


class S3Base(unittest.TestCase):
    """S1 迁移库 + BTCUSDT EVENT 成交（费用状态按用例定制）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "l.db")
        led = Ledger(self.path)
        led.create_intent("I1", "BTCUSDT", "LONG", 0.25)
        led.record_order_submitting(
            client_order_id="C1", intent_id="I1", order_kind="ENTRY",
            side="BUY", position_side="LONG", quantity=0.25)
        led.insert_fill("F1", "C1", 0.25, 100.5, 0.5, "BUY", "t1")
        led.close()
        fm.migrate_fills_identity(self.path)
        self.led = Ledger(self.path)
        self.addCleanup(self.led.close)
        self.fill_ref = "BTCUSDT:EF1"

    def _venue_fill(self, fill_id="EF1", fee_raw=None, fee_asset=None):
        self.led.insert_fill(
            fill_id, "C1", 0.25, 100.5, float(fee_raw or 0), "BUY", "t1",
            venue_symbol="BTCUSDT", venue_qty_raw="0.25",
            venue_price_raw="100.5", venue_fee_raw=fee_raw,
            venue_fee_asset=fee_asset, venue_derivation_ctx="ctx")

    def _supp(self, **kw):
        params = dict(stable_event_id="ST1", fill_ref=self.fill_ref,
                      fee_raw_s="0.5", fee_asset_s="USDT",
                      observed_at="t2")
        params.update(kw)
        return fp.record_fee_supplement(self.led, **params)

    def _effects(self):
        return self.led.fee_effect_rows(self.fill_ref)

    def _proj(self):
        return fp.effective_fee(self.led, self.fill_ref)


class T_F2e_EntrySemantics(S3Base):
    """T-F2e：声明 KNOWN 才强制 raw+asset（F4 口径；schema CHECK 同验）。"""

    def test_known_declaration_requires_finite_raw_and_asset(self):
        self._venue_fill()
        with self.assertRaises(SafetyViolation):
            self._supp(fee_raw_s="abc")           # 非法 raw
        with self.assertRaises(SafetyViolation):
            self._supp(fee_raw_s="0.5", fee_asset_s="")  # KNOWN 缺资产
        with self.assertRaises(SafetyViolation):
            self._supp(fee_raw_s="NaN")
        # 合法 UNKNOWN 观察可入账（不强制任何字段）
        out = self._supp(fee_raw_s=None, fee_asset_s=None,
                         stable_event_id="STU")
        self.assertEqual(out["verdict"], "INCOMPLETE")

    def test_schema_check_enforces_pairing(self):
        self._venue_fill()
        self.led.ensure_fee_projection_schema()
        with self.assertRaises(sqlite3.IntegrityError):
            self.led._conn.execute(
                "INSERT INTO fill_fee_supplements (stable_event_id,"
                " fill_ref, fee_raw_s, fee_asset_s, observed_at,"
                " recorded_at) VALUES ('SX', ?, '0.5', NULL, 't', 't')",
                (self.fill_ref,))


class T_F4_NumericEquality(S3Base):
    """T-F4：Decimal 数值相等与表示无关；微差必不等。"""

    def test_numeric_equality_representation_independent(self):
        self.assertIs(fp.fee_values_equal("-0.400", "-0.4"), True)
        self.assertIs(fp.fee_values_equal("0.4", "0.40"), True)
        # 默认 prec=28 的加法会把 1e-300 抹掉，夹具必须在足够精度下构造原始串。
        with localcontext() as ctx:
            ctx.prec = 400
            near = format(Decimal("0.4") + Decimal("1e-300"), "f")
        self.assertNotEqual(near, "0.4")
        self.assertIs(fp.fee_values_equal("0.40", near), False)
        over = "0." + "1" * (fp.PREC_CAP + 1)
        other = "0." + "2" * (fp.PREC_CAP + 1)
        with self.assertRaises(fp.ComparisonRefused):
            fp.fee_values_equal(over, other)
        with self.assertRaises(fp.ComparisonRefused):
            fp.fee_values_equal(over, over)
        self.assertIs(fp.fee_values_equal(None, "0.4"), None)
        self.assertIs(fp.fee_values_equal(None, "0.4"), None)
        self.assertIs(fp.fee_values_equal("0.4", None), None)
        self.assertIs(fp.fee_values_equal(None, None), None)


class T_F4R_LegacyFloatExcluded(S3Base):
    """T-F4R：历史 float 不参与比较——基线一律 UNKNOWN，无伪差冲突。"""

    def test_legacy_float_fee_never_produces_conflict(self):
        # 历史行：fee_raw NULL（迁移置空），float fee=0.5 仅展示
        row = self.led._conn.execute(
            "SELECT fee, fee_raw FROM fills WHERE fill_id='F1'").fetchone()
        self.assertGreater(float(row["fee"]), 0)  # 展示值存在
        self.assertIsNone(row["fee_raw"])          # 基线 UNKNOWN
        # 迁移后的历史行 symbol 为空，限定引用无法消解。
        # 只补归属，不填 fee_raw，float 展示值仍不参与比较。
        self.led._conn.execute(
            "UPDATE fills SET symbol='BTCUSDT'"
            " WHERE fill_id='F1' AND fee_raw IS NULL")
        self.led._conn.commit()
        ref = "BTCUSDT:F1"
        out = fp.record_fee_supplement(
            self.led, stable_event_id="STR", fill_ref=ref,
            fee_raw_s="0.7", fee_asset_s="USDT", observed_at="t")
        self.assertEqual(out["verdict"], "KNOWN")
        eff = fp.effective_fee(self.led, ref)
        self.assertEqual(eff["status"], "KNOWN")
        self.assertEqual(eff["effective_raw"], "0.7")


class T_FP1_FirstDeterminationOnce(S3Base):
    """T-FP1：UNKNOWN+单补充→投影 v1 全额一次；重放零新增。"""

    def test_unknown_single_supplement_projects_v1_once(self):
        self._venue_fill()  # fee UNKNOWN
        out = self._supp(stable_event_id="ST1")
        self.assertEqual(out["verdict"], "KNOWN")
        self.assertEqual(out["rule"], "②")
        eff = self._proj()
        self.assertEqual(eff["projection_version"], 1)
        self.assertEqual(eff["effective_raw"], "0.5")
        self.assertEqual(eff["effective_asset"], "USDT")
        effects = self._effects()
        self.assertEqual(len(effects), 1)
        self.assertEqual(effects[0]["kind"], "APPLY")
        self.assertEqual(effects[0]["amount_raw"], "0.5")
        self.assertIn(":v1:", effects[0]["effect_key"])
        # 同稳定 ID 重放 → 零新增（补充/投影/效果全不变）
        out2 = self._supp(stable_event_id="ST1")
        self.assertTrue(out2["replayed"])
        self.assertEqual(out2["verdict"], "KNOWN")
        self.assertEqual(len(self.led.fee_supplements(self.fill_ref)), 1)
        self.assertEqual(len(self._effects()), 1)
        self.assertEqual(self._proj()["projection_version"], 1)

    def test_same_stable_id_different_content_conflicts(self):
        self._venue_fill()
        self._supp(stable_event_id="ST1", fee_raw_s="0.5")
        with self.assertRaises(fp.FeeConflict):
            self._supp(stable_event_id="ST1", fee_raw_s="0.9")
        self.assertEqual(len(self.led.fee_supplements(self.fill_ref)), 1)


class T_FP2_DoubleUnknownIncomplete(S3Base):
    """T-FP2：双 UNKNOWN→INCOMPLETE：不投影、不写 0、不判重复。"""

    def test_double_unknown_stays_incomplete(self):
        self._venue_fill()  # 基线 UNKNOWN
        out = self._supp(stable_event_id="ST1", fee_raw_s=None,
                         fee_asset_s=None)  # UNKNOWN 观察
        self.assertEqual(out["verdict"], "INCOMPLETE")
        eff = self._proj()
        self.assertEqual(eff["status"], "INCOMPLETE")
        self.assertIsNone(eff["effective_raw"])  # 非 0
        self.assertEqual(eff["projection_version"], 0)
        self.assertEqual(self._effects(), [])
        self.assertIsNone(self.led.fee_projection_row(self.fill_ref))
        # 再来一条 UNKNOWN 仍 INCOMPLETE（非重复、非冲突）
        out2 = self._supp(stable_event_id="ST2", fee_raw_s=None,
                          fee_asset_s=None)
        self.assertEqual(out2["verdict"], "INCOMPLETE")
        self.assertEqual(self._effects(), [])


class T_FP3_ConflictRetainsBaseline(S3Base):
    """T-FP3：KNOWN 基线+冲突补充→FEE_CONFLICT：原值保留不覆盖。"""

    def test_known_baseline_conflicting_supplement(self):
        self._venue_fill(fee_raw="0.5", fee_asset="USDT")
        out = self._supp(stable_event_id="ST1", fee_raw_s="0.9",
                         fee_asset_s="USDT")
        self.assertEqual(out["verdict"], "FEE_CONFLICT")
        eff = self._proj()
        self.assertEqual(eff["status"], "CONFLICTED")
        self.assertEqual(eff["effective_raw"], "0.5")  # V0 保留
        self.assertEqual(eff["projection_version"], 0)  # 无新版本
        self.assertEqual(self._effects(), [])           # 无效果
        # 资产不同同样冲突（离散事实暴露）
        out2 = self._supp(stable_event_id="ST2", fee_raw_s="0.5",
                          fee_asset_s="BNB")
        self.assertEqual(out2["verdict"], "FEE_CONFLICT")


class T_FP4_OnlyExplicitCorrectionRecomputes(S3Base):
    """T-FP4：补充到达不触发重算；仅显式修正产生 delta。"""

    def test_supplement_never_recomputes_correction_does_delta(self):
        self._venue_fill()
        self._supp(stable_event_id="ST1", fee_raw_s="0.5")
        v1 = self._proj()
        self.assertEqual(v1["projection_version"], 1)
        # 一致补充到达（不同稳定 ID，同值）→ 无新版本无效果
        out = self._supp(stable_event_id="ST2", fee_raw_s="0.500",
                         fee_asset_s="USDT")
        self.assertEqual(out["rule"], "①")
        self.assertEqual(self._proj()["projection_version"], 1)
        self.assertEqual(len(self._effects()), 1)
        # 显式修正（带凭据）→ v2 只应用差额
        corr = fp.apply_fee_correction(
            self.led, fill_ref=self.fill_ref, new_fee_raw="0.8",
            new_fee_asset="USDT", credential_ref="order:C1")
        self.assertEqual(corr["mode"], "DELTA")
        self.assertEqual(corr["delta_raw"], "0.3")
        self.assertEqual(self._proj()["projection_version"], 2)
        effects = self._effects()
        self.assertEqual(len(effects), 2)
        self.assertEqual(effects[1]["amount_raw"], "0.3")  # delta 非全额
        self.assertNotEqual(effects[1]["amount_raw"], "0.8")


class T_FP5_EffectKeyIdempotency(S3Base):
    """T-FP5：同 effect_key 重放被 UNIQUE 拒；旧版本键不可复活。"""

    def test_effect_key_replay_rejected_and_old_key_dead(self):
        self._venue_fill()
        self._supp(stable_event_id="ST1", fee_raw_s="0.5")
        key_v1 = self._effects()[0]["effect_key"]
        # 同 key 重放（直接注入）→ UNIQUE 拒绝
        with self.assertRaises(sqlite3.IntegrityError):
            self.led._conn.execute(
                "INSERT INTO fee_effect_ledger (effect_key, kind,"
                " amount_raw, asset, fill_ref, written_at)"
                " SELECT effect_key, kind, amount_raw, asset, fill_ref,"
                " 't2' FROM fee_effect_ledger WHERE effect_key=?",
                (key_v1,))
        self.led._conn.rollback()
        # 修正到 v2 后，旧版本键不可复活（再次写入 v1 键仍被拒）
        fp.apply_fee_correction(
            self.led, fill_ref=self.fill_ref, new_fee_raw="0.8",
            new_fee_asset="USDT", credential_ref="order:C1")
        with self.assertRaises(sqlite3.IntegrityError):
            self.led._conn.execute(
                "INSERT INTO fee_effect_ledger (effect_key, kind,"
                " amount_raw, asset, fill_ref, written_at)"
                " VALUES (?, 'APPLY', '0.5', 'USDT', ?, 't3')",
                (key_v1, self.fill_ref))
        keys = [e["effect_key"] for e in self._effects()]
        self.assertTrue(any(":v2:" in k for k in keys))


class T_FP6_ThreeStepAtomic(S3Base):
    """T-FP6：三步单事务——c 步失败 a 步回滚；调用方事务拒绝。"""

    def test_effect_failure_rolls_back_supplement(self):
        self._venue_fill()
        self.led.ensure_fee_projection_schema()
        # 预占 v1 效果键 → 步骤 c 必然 UNIQUE 失败
        self.led._conn.execute(
            "INSERT INTO fee_effect_ledger (effect_key, kind,"
            " amount_raw, asset, fill_ref, written_at) VALUES"
            " (?, 'APPLY', '9', 'USDT', ?, 't0')",
            (f"{self.fill_ref}:FEE:v1:USDT", self.fill_ref))
        self.led._conn.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self._supp(stable_event_id="ST1", fee_raw_s="0.5")
        # 补充已回滚（无"已补充未投影"中间态）
        self.assertEqual(self.led.fee_supplements(self.fill_ref), [])
        self.assertIsNone(self.led.fee_projection_row(self.fill_ref))

    def test_projection_step_failure_rolls_back_supplement(self):
        self._venue_fill()
        real = self.led._conn.execute
        calls = {"n": 0}

        def flaky(sql, *a, **k):
            if "fill_fee_projection" in sql and calls["n"] > 0:
                raise sqlite3.OperationalError("injected b-step failure")
            if "fill_fee_projection" in sql:
                calls["n"] += 1
            return real(sql, *a, **k)
        class _ConnProxy:
            def __init__(self, inner):
                self._inner = inner

            def execute(self, sql, *a, **k):
                return flaky(sql, *a, **k)

            def __getattr__(self, name):
                return getattr(self._inner, name)

        self.led._conn = _ConnProxy(self.led._conn)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                self._supp(stable_event_id="ST1", fee_raw_s="0.5")
        finally:
            self.led._conn = real.__self__
        self.assertEqual(self.led.fee_supplements(self.fill_ref), [])

    def test_caller_open_transaction_refused_before_write(self):
        self._venue_fill()
        c = self.led._conn
        c.execute("BEGIN")
        c.execute("UPDATE orders SET avg_price=123"
                  " WHERE client_order_id='C1'")
        with self.assertRaises(SafetyViolation):
            self._supp(stable_event_id="ST1")
        with self.assertRaises(SafetyViolation):
            fp.apply_fee_correction(
                self.led, fill_ref=self.fill_ref, new_fee_raw="0.8",
                new_fee_asset="USDT", credential_ref="order:C1")
        c.rollback()
        avg = c.execute("SELECT avg_price FROM orders"
                        " WHERE client_order_id='C1'").fetchone()[0]
        self.assertNotEqual(avg, 123.0)  # 调用方 rollback 有效
        self.assertEqual(self.led.fee_supplements(self.fill_ref), [])


class T_FP7_ConsistentSupplementZeroImpact(S3Base):
    """T-FP7：一致补充→零经济影响（幂等，无新版本）。"""

    def test_consistent_supplement_zero_impact(self):
        self._venue_fill(fee_raw="0.5", fee_asset="USDT")
        booking = self.led._conn.execute(
            "SELECT fee, fee_raw, economic_effect_applied FROM fills"
            " WHERE symbol='BTCUSDT' AND fill_id='EF1'").fetchone()
        self.assertEqual(booking["fee_raw"], "0.5")
        self.assertEqual(int(booking["economic_effect_applied"]), 1)
        self.assertGreater(float(booking["fee"]), 0)
        fees_before = self.led.accounting_aggregate()["total_fees"]
        out = self._supp(stable_event_id="ST1", fee_raw_s="0.5000")
        self.assertEqual(out["verdict"], "KNOWN")
        self.assertEqual(out["rule"], "①")
        eff = self._proj()
        self.assertEqual(eff["status"], "KNOWN")
        self.assertEqual(eff["effective_raw"], "0.5")  # 基线原值
        self.assertEqual(eff["projection_version"], 0)
        self.assertEqual(self._effects(), [])  # 补充不另扣一笔
        booking_after = self.led._conn.execute(
            "SELECT fee, fee_raw, economic_effect_applied FROM fills"
            " WHERE symbol='BTCUSDT' AND fill_id='EF1'").fetchone()
        self.assertEqual(booking_after["fee"], booking["fee"])
        self.assertEqual(booking_after["fee_raw"], "0.5")
        self.assertEqual(int(booking_after["economic_effect_applied"]), 1)
        self.assertEqual(
            self.led.accounting_aggregate()["total_fees"], fees_before)
        again = self._supp(stable_event_id="ST2", fee_raw_s="0.5")
        self.assertEqual(again["rule"], "①")
        self.assertEqual(self._effects(), [])
        self.assertEqual(
            self.led.accounting_aggregate()["total_fees"], fees_before)


class T_FP8_ConflictedIsolatedNoAutoDelta(S3Base):
    """T-FP8：冲突→CONFLICTED 隔离+告警，零自动差额；仅修正放行。"""

    def test_conflicting_supplements_isolated_then_correction(self):
        self._venue_fill()
        self._supp(stable_event_id="ST1", fee_raw_s="0.5")
        out = self._supp(stable_event_id="ST2", fee_raw_s="0.9")
        self.assertEqual(out["verdict"], "FEE_CONFLICT")
        eff = self._proj()
        self.assertEqual(eff["status"], "CONFLICTED")
        self.assertEqual(eff["projection_version"], 1)  # v1 保留
        self.assertEqual(eff["effective_raw"], "0.5")
        self.assertEqual(len(self._effects()), 1)       # 无新增效果
        # 后续一致补充也不自动解决
        out2 = self._supp(stable_event_id="ST3", fee_raw_s="0.5")
        self.assertEqual(out2["verdict"], "FEE_CONFLICT")
        self.assertEqual(len(self._effects()), 1)
        # 唯一通道：带凭据显式修正 → 新版本 + delta
        corr = fp.apply_fee_correction(
            self.led, fill_ref=self.fill_ref, new_fee_raw="0.7",
            new_fee_asset="USDT", credential_ref="order:C1")
        self.assertEqual(corr["mode"], "DELTA")
        self.assertEqual(self._proj()["projection_version"], 2)
        self.assertEqual(self._effects()[-1]["amount_raw"], "0.2")

    def test_correction_requires_credential(self):
        self._venue_fill()
        self._supp(stable_event_id="ST1", fee_raw_s="0.5")
        with self.assertRaises(SafetyViolation):
            fp.apply_fee_correction(
                self.led, fill_ref=self.fill_ref, new_fee_raw="0.7",
                new_fee_asset="USDT", credential_ref="")
        with self.assertRaises(SafetyViolation):
            fp.apply_fee_correction(
                self.led, fill_ref=self.fill_ref, new_fee_raw="0.7",
                new_fee_asset="USDT",
                credential_ref="order:NOPE plus note")  # 悬空+附加文字


class T_FP9_CrossAssetDoubleLeg(S3Base):
    """T-FP9：跨资产修正→按资产双蹄同事务；无跨单位相减。"""

    def test_cross_asset_correction_double_leg_atomic(self):
        self._venue_fill()
        self._supp(stable_event_id="ST1", fee_raw_s="0.5",
                   fee_asset_s="USDT")
        corr = fp.apply_fee_correction(
            self.led, fill_ref=self.fill_ref, new_fee_raw="0.01",
            new_fee_asset="BNB", credential_ref="order:C1")
        self.assertEqual(corr["mode"], "DOUBLE_LEG")
        self.assertIsNone(corr["delta_raw"])  # 无跨单位相减
        effects = self._effects()
        self.assertEqual(len(effects), 3)     # v1 APPLY + 两蹄
        rev = [e for e in effects if e["kind"] == "REVERSE"]
        app = [e for e in effects if e["kind"] == "APPLY"]
        self.assertEqual(len(rev), 1)
        self.assertEqual(rev[0]["amount_raw"], "0.5")  # 旧资产全额
        self.assertEqual(rev[0]["asset"], "USDT")
        self.assertIn(":v2:USDT", rev[0]["effect_key"])
        self.assertEqual(len(app), 2)
        new_leg = [e for e in app if e["asset"] == "BNB"][0]
        self.assertEqual(new_leg["amount_raw"], "0.01")  # 新资产全额
        self.assertIn(":v2:BNB", new_leg["effect_key"])
        self.assertEqual(self._proj()["effective_asset"], "BNB")
        self.assertEqual(self._proj()["effective_raw"], "0.01")

    def test_leg_evidence_insufficient_neither_applied(self):
        # CONFLICTED 且无保留有效值（基线 UNKNOWN+冲突补充）→
        # REVERSE 蹄证据不足 → 两蹄都不应用
        self._venue_fill()
        self._supp(stable_event_id="ST1", fee_raw_s="0.5",
                   fee_asset_s="USDT")
        self._supp(stable_event_id="ST2", fee_raw_s="0.9",
                   fee_asset_s="USDT")
        self.assertEqual(self._proj()["status"], "CONFLICTED")
        with self.assertRaises(SafetyViolation):
            fp.apply_fee_correction(
                self.led, fill_ref=self.fill_ref, new_fee_raw="0.01",
                new_fee_asset="BNB", credential_ref="order:C1")
        effects = self._effects()
        self.assertEqual(len(effects), 1)  # 仅 v1，双蹄未应用
        self.assertEqual(self._proj()["projection_version"], 1)
        self.assertEqual(self._proj()["effective_asset"], "USDT")


class T_F6a_LongTailLossless(S3Base):
    """T-F6a：30+ 位有效位差值全尾保留（默认 prec28 对照丢尾）。"""

    def test_long_tail_subtraction_lossless(self):
        a = "1.23456789012345678901234567890123"   # 32 位有效
        b = "1"
        precise = fp.precise_sub(a, b)
        self.assertEqual(
            precise, "0.23456789012345678901234567890123")
        # 对照：默认上下文丢尾（证明陷阱方案的必要性）
        with mock.patch("aurora.kernel.fee_projection.PREC_FLOOR", 28), \
             mock.patch("aurora.kernel.fee_projection.PREC_EXTRA", 0):
            pass  # 对照直接用默认上下文计算
        naive = str(Decimal(a) - Decimal(b))
        self.assertNotEqual(naive, precise)
        self.assertTrue(naive.startswith("0.234567890123456789012345"))
        self.assertLess(len(naive), len(precise))  # 28 位截断


class T_F6b_InputBoundsRefusal(S3Base):
    """T-F6b：|adjusted|>999999/非有限入口拒收；扩精度仍 Inexact 拒绝。"""

    def test_entry_bounds_rejected(self):
        self._venue_fill()
        with self.assertRaises(SafetyViolation):
            self._supp(fee_raw_s="1e1000000")   # adjusted 超界
        with self.assertRaises(SafetyViolation):
            self._supp(fee_raw_s="Infinity")     # 非有限
        with self.assertRaises(SafetyViolation):
            fp.apply_fee_correction(
                self.led, fill_ref=self.fill_ref, new_fee_raw="1e1000000",
                new_fee_asset="USDT", credential_ref="order:C1")
        self.assertEqual(self.led.fee_supplements(self.fill_ref), [])

    def test_inexact_after_retry_refused(self):
        # 2 万位有效位差值：扩精度一次仍 Inexact（prec 上限 10000）
        # → 拒绝入账并告警，绝不静默截断
        huge = "0." + "1" * 20000
        with self.assertRaises(fp.PrecisionRefused):
            fp.precise_sub(huge, "0.1")
        self.assertEqual(fp._attempt_precs(28), [28, 56])
        self.assertEqual(fp._attempt_precs(6000), [6000, fp.PREC_CAP])
        self.assertEqual(fp._attempt_precs(fp.PREC_CAP), [fp.PREC_CAP])
        self.assertTrue(all(p <= fp.PREC_CAP
                            for p in fp._attempt_precs(6000)))
        with self.assertRaises(fp.PrecisionRefused):
            fp._attempt_precs(fp.PREC_CAP + 1)
        # 正常范围仍无损
        self.assertEqual(fp.precise_sub("1.5", "0.5"), "1.0")

    def test_correction_with_inexact_refused_nothing_applied(self):
        self._venue_fill()
        self._supp(stable_event_id="ST1", fee_raw_s="0.5",
                   fee_asset_s="USDT")
        huge = "0." + "1" * 20000
        with self.assertRaises(fp.PrecisionRefused):
            fp.apply_fee_correction(
                self.led, fill_ref=self.fill_ref, new_fee_raw=huge,
                new_fee_asset="USDT", credential_ref="order:C1")
        self.assertEqual(len(self._effects()), 1)  # 未新增
        self.assertEqual(self._proj()["projection_version"], 1)

    def test_formula_over_cap_refused_without_truncation(self):
        # 操作数 9997 位未超 10000，公式 max+4 = 10001，必须拒绝
        operand = "1" * 9997
        self.assertLessEqual(
            len(Decimal(operand).as_tuple().digits), fp.PREC_CAP)
        with self.assertRaises(fp.PrecisionRefused) as caught:
            fp.precise_sub(operand, "0")
        self.assertIn("10001", str(caught.exception))


class S3_01_UnknownSupplementDoesNotRebook(S3Base):
    """S3-01：UNKNOWN 补充不能触发已知基线的再次全额记账。"""

    def test_unknown_supplement_does_not_rebook_known_baseline(self):
        self._venue_fill(fee_raw="0.5", fee_asset="USDT")
        self.assertIsNone(self.led.fee_projection_row(self.fill_ref))
        out = self._supp(stable_event_id="STU", fee_raw_s=None,
                         fee_asset_s=None)
        self.assertNotEqual(out["rule"], "②")
        self.assertEqual(out["effect_keys"], [])
        self.assertEqual(self._effects(), [])
        eff = self._proj()
        self.assertEqual(eff["status"], "KNOWN")
        self.assertEqual(eff["effective_raw"], "0.5")
        self.assertEqual(eff["effective_asset"], "USDT")
        self.assertEqual(eff["projection_version"], 0)


class S3_02_CorrectionSeesBookedBaseline(S3Base):
    """S3-02：无投影行仍须识别已记账基线。"""

    def test_same_asset_correction_is_delta_not_full_apply(self):
        self._venue_fill(fee_raw="0.5", fee_asset="USDT")
        self.assertIsNone(self.led.fee_projection_row(self.fill_ref))
        corr = fp.apply_fee_correction(
            self.led, fill_ref=self.fill_ref, new_fee_raw="0.7",
            new_fee_asset="USDT", credential_ref="order:C1")
        self.assertEqual(corr["mode"], "DELTA")
        self.assertEqual(corr["delta_raw"], "0.2")
        effects = self._effects()
        self.assertEqual(len(effects), 1)
        self.assertEqual(effects[0]["amount_raw"], "0.2")
        self.assertNotEqual(effects[0]["amount_raw"], "0.7")

    def test_cross_asset_correction_reverses_booked_baseline(self):
        self._venue_fill(fee_raw="0.5", fee_asset="USDT")
        corr = fp.apply_fee_correction(
            self.led, fill_ref=self.fill_ref, new_fee_raw="0.01",
            new_fee_asset="BNB", credential_ref="order:C1")
        self.assertEqual(corr["mode"], "DOUBLE_LEG")
        self.assertIsNone(corr["delta_raw"])
        effects = self._effects()
        self.assertEqual(len(effects), 2)
        rev = [e for e in effects if e["kind"] == "REVERSE"]
        app = [e for e in effects if e["kind"] == "APPLY"]
        self.assertEqual(len(rev), 1)
        self.assertEqual(rev[0]["amount_raw"], "0.5")
        self.assertEqual(rev[0]["asset"], "USDT")
        self.assertEqual(len(app), 1)
        self.assertEqual(app[0]["amount_raw"], "0.01")
        self.assertEqual(app[0]["asset"], "BNB")


class S3_03_ResolutionStaysInForce(S3Base):
    """S3-03：显式解决之后，旧证据重放不能推翻；新冲突仍暴露。"""

    def test_resolved_projection_survives_replay_and_matching_supplement(self):
        self._venue_fill()
        self._supp(stable_event_id="ST1", fee_raw_s="0.5")
        self._supp(stable_event_id="ST2", fee_raw_s="0.8")
        self.assertEqual(self._proj()["status"], "CONFLICTED")
        fp.apply_fee_correction(
            self.led, fill_ref=self.fill_ref, new_fee_raw="0.7",
            new_fee_asset="USDT", credential_ref="order:C1")
        self.assertEqual(self._proj()["status"], "KNOWN")
        self.assertEqual(self._proj()["projection_version"], 2)
        self.assertEqual(self._proj()["effective_raw"], "0.7")
        replay = self._supp(stable_event_id="ST1", fee_raw_s="0.5")
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["verdict"], "KNOWN")
        self.assertEqual(replay["version"], 2)
        self.assertEqual(self._proj()["status"], "KNOWN")
        matched = self._supp(stable_event_id="ST3", fee_raw_s="0.7")
        self.assertEqual(matched["rule"], "①")
        self.assertEqual(self._proj()["status"], "KNOWN")
        self.assertEqual(self._proj()["projection_version"], 2)
        self.assertEqual(self._proj()["effective_raw"], "0.7")
        fresh = self._supp(stable_event_id="ST4", fee_raw_s="0.9")
        self.assertEqual(fresh["verdict"], "FEE_CONFLICT")
        self.assertEqual(self._proj()["status"], "CONFLICTED")
        self.assertEqual(self._proj()["effective_raw"], "0.7")
        self.assertEqual(self._proj()["projection_version"], 2)


class S3_04_ReadFailureIsNotEmpty(S3Base):
    """S3-04：真实读取故障上抛并回滚；缺表才是空。"""

    def test_locked_supplement_read_rolls_back_whole_write(self):
        self._venue_fill()
        self._supp(stable_event_id="ST1", fee_raw_s="0.5")
        real = self.led._conn.execute

        def flaky(sql, *a, **k):
            if "supplement_rowid" in sql:
                raise sqlite3.OperationalError("database is locked")
            return real(sql, *a, **k)

        class _ConnProxy:
            def execute(self, sql, *a, **k):
                return flaky(sql, *a, **k)

            def __getattr__(self, name):
                return getattr(real.__self__, name)

        self.led._conn = _ConnProxy()
        try:
            with self.assertRaises(sqlite3.OperationalError):
                self._supp(stable_event_id="ST2", fee_raw_s="0.8")
        finally:
            self.led._conn = real.__self__
        kept = self.led.fee_supplements(self.fill_ref)
        self.assertEqual([s["fee_raw_s"] for s in kept], ["0.5"])
        self.assertEqual(self._proj()["status"], "KNOWN")
        self.assertEqual(self._proj()["effective_raw"], "0.5")

    def test_absent_table_is_empty_locked_read_is_raised(self):
        self.led.ensure_fee_projection_schema()
        real = self.led._conn.execute

        def locked(sql, *a, **k):
            raise sqlite3.OperationalError("database is locked")

        class _ConnProxy:
            def execute(self, sql, *a, **k):
                return locked(sql, *a, **k)

            def __getattr__(self, name):
                return getattr(real.__self__, name)

        self.led._conn = _ConnProxy()
        try:
            for call in (
                lambda: self.led.fee_supplements(self.fill_ref),
                lambda: self.led.fee_projection_row(self.fill_ref),
                lambda: self.led.fee_effect_rows(self.fill_ref),
                lambda: self.led.fee_correction_records(self.fill_ref),
            ):
                with self.assertRaises(sqlite3.OperationalError):
                    call()
        finally:
            self.led._conn = real.__self__
        c = self.led._conn
        for table, call, empty in (
            ("fill_fee_supplements",
             lambda: self.led.fee_supplements(self.fill_ref), []),
            ("fill_fee_projection",
             lambda: self.led.fee_projection_row(self.fill_ref), None),
            ("fee_effect_ledger",
             lambda: self.led.fee_effect_rows(self.fill_ref), []),
            ("fee_corrections",
             lambda: self.led.fee_correction_records(self.fill_ref), []),
        ):
            c.execute(f"DROP TABLE {table}")
            self.assertEqual(call(), empty)


if __name__ == "__main__":
    unittest.main()
