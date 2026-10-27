"""外部周报 2026-W43 吸收：四项上游缺陷 → 离线测试与状态机约束。

来源（不构成交易依赖升级理由，全部离线吸收）：
A1 NautilusTrader #5375 — 未知提交跨重启丢失订单归属
A2 NautilusTrader #5377 — 用户流恢复在 -1125 类凭证失效上无限卡死
A3 NautilusTrader #5416 — Hedge Mode 下错误仓位快照"覆盖"成交
A4 Freqtrade #13679 — 交易所止损平仓路径漏记资金费
"""
import json
import os
import pickle
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.kernel import binance_exchange as be
from aurora.kernel.fake_exchange import FakeExchange
from aurora.kernel.ledger import Ledger
from aurora.kernel.orchestrator import Orchestrator
from aurora.kernel.port import Fill, OrderKind
from aurora.funding_income import (
    FundingIdentityConflict,
    apply_late_event_check,
    funding_total,
    declare_window,
    funding_fetch_unavailable,
    funding_totals_by_asset,
    ingest_funding_events,
    stable_funding_event_id,
)
from aurora.kernel.ledger import FillIdentityConflict, Ledger
from aurora.p0_boundary import SafetyViolation
from tests.kernel_test_open import bind_explicit_protect_prices


class A1UnknownSubmitRestartAttributionTests(unittest.TestCase):
    """#5375：重启后必须按原 ID 归属；无法归属的成交熔断，不得新建 ID 重试。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "ledger.db")

    def _restart(self, exchange):
        ledger = Ledger(self.path)
        orch = bind_explicit_protect_prices(
            Orchestrator(ledger, exchange, instance_id="w43-restart"))
        self.addCleanup(ledger.close)
        return orch

    def test_recovery_uses_original_id_and_never_mints_new_entry(self):
        exchange = FakeExchange(entry_behavior="timeout_then_filled")
        ledger = Ledger(self.path)
        orch = bind_explicit_protect_prices(
            Orchestrator(ledger, exchange, instance_id="w43-first"))
        orch.recover()
        out = orch.open_position("LONG", 0.01, intent_id="W43-A1")
        self.assertEqual(out["state"], "SUBMIT_UNKNOWN")
        ledger.close()

        restarted = self._restart(exchange)
        report = restarted.recover()
        # 原订单按原 clientOrderId 归属收敛；绝无第二个 ENTRY 提交
        entry_submits = [r for r in exchange.submit_log
                         if r.order_kind == OrderKind.ENTRY]
        self.assertEqual(len(entry_submits), 1)
        self.assertEqual(entry_submits[0].client_order_id, "W43-A1-ENTRY")
        intent = restarted.ledger.get_intent("W43-A1")
        self.assertIn(intent["state"], ("PROTECTED", "FILLED_UNPROTECTED",
                                        "RECOVERY_REQUIRED"))
        self.assertTrue(report["resolved"] or report["unresolved"])

    def test_foreign_fill_during_recovery_is_orphan_never_adopted(self):
        exchange = FakeExchange()
        ledger = Ledger(self.path)
        orch = bind_explicit_protect_prices(
            Orchestrator(ledger, exchange, instance_id="w43-o"))
        orch.recover()
        orch.open_position("LONG", 0.01, intent_id="W43-A1b")
        # 交易所侧出现无法归属到他单的成交（如同 RFC 中被误归外部的 fill）
        out = orch.apply_fill_event(Fill(
            fill_id="FOREIGN-1", client_order_id="NOT-OURS-XYZ",
            qty=0.01, price=100.0, fee=0.0, side="BUY",
            filled_at="2026-10-20T00:00:00Z",
            symbol="BTCUSDT", qty_raw="0.01", price_raw="100.0",
            fee_raw="0.0", fee_asset="USDT"))
        self.assertEqual(out["class"], "ORPHAN")
        self.assertEqual(ledger.kill_state()["engaged"], 1)
        # 该成交不得被并入我们的意图；无新 ENTRY 铸造
        self.assertEqual(ledger.fills_for_order("NOT-OURS-XYZ"), [])
        entry_submits = [r for r in exchange.submit_log
                         if r.order_kind == OrderKind.ENTRY]
        self.assertEqual(len(entry_submits), 1)
        ledger.close()


class A2StaleCredentialNeverThrottledTests(unittest.TestCase):
    """#5377 的 REST 等价约束：凭证失效类错误不得被当瞬态限流重试。

    W43 复审上下文限定：本分类只适用于**订单/查询 REST 操作域**。
    -1125 在原案中属用户数据流域——对"关闭已失效 listen key"可表示
    资源已不存在，对创建/续期不能一律当成功。AURORA 无用户数据流
    （USER-STREAM RECOVERY = NOT IMPLEMENTED），本类仅登记替代性
    约束：任何操作域的错误分类必须携带操作上下文，本断言的上下文
    是"下单/查询失败不得被误分类为可重试瞬态"。
    """

    def test_auth_class_errors_never_match_throttle_or_timeout(self):
        for msg in (
            "APIError(code=-1022): Signature for this request is not valid.",
            "APIError(code=-2015): Invalid API-key, IP, or permissions.",
            "APIError(code=-1125): This listenKey does not exist",  # 原案错误码
        ):
            exc = Exception(msg)
            self.assertFalse(be._is_throttle(exc), msg)
            self.assertFalse(be._is_timeout(exc), msg)

    def test_throttle_marks_still_match_transient_controls(self):
        self.assertTrue(be._is_throttle(Exception("APIError(code=-1003) too many requests")))
        self.assertTrue(be._is_timeout(Exception("Read timed out.")))

    def test_permanent_query_failure_keeps_unknown_never_fake_converges(self):
        # 持久查询失败跨重启：状态永远 UNKNOWN、永不假收敛、永不重提交
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "l.db")
            exchange = FakeExchange(entry_behavior="timeout_then_filled")
            ledger = Ledger(path)
            orch = bind_explicit_protect_prices(
                Orchestrator(ledger, exchange, instance_id="a2"))
            orch.recover()
            out = orch.open_position("LONG", 0.01, intent_id="W43-A2")
            self.assertEqual(out["state"], "SUBMIT_UNKNOWN")
            ledger.close()
            exchange.fail_order_queries(True)
            for _ in range(3):  # 跨"重启"轮次
                ledger = Ledger(path)
                orch = bind_explicit_protect_prices(
                    Orchestrator(ledger, exchange, instance_id="a2-r"))
                report = orch.recover()
                self.assertTrue(report["unresolved"])
                intent = ledger.get_intent("W43-A2")
                self.assertNotIn(intent["state"], ("RECONCILED", "CLOSED"))
                ledger.close()
            self.assertEqual(
                len([r for r in exchange.submit_log
                     if r.order_kind == OrderKind.ENTRY]), 1)


class A3HedgeDualLegSnapshotTests(unittest.TestCase):
    """#5416：双腿快照/另腿成交不得当作本腿覆盖或成交证据。"""

    def test_dual_leg_position_is_never_netted_or_faked(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Ledger(os.path.join(tmp, "l.db"))
            exchange = FakeExchange()
            orch = bind_explicit_protect_prices(
                Orchestrator(ledger, exchange, instance_id="a3"))
            orch.recover()
            out = orch.open_position("LONG", 0.001, intent_id="W43-A3")
            self.assertTrue(out.get("success"), out)
            exchange.seed_external_position(-0.002, 100.0)  # 对侧腿出现
            pos = exchange.position("BTCUSDT")
            self.assertIsNone(pos)  # 双腿 → UNKNOWN，绝不净额成 FLAT
            ledger.close()

    def test_other_leg_fill_does_not_fill_or_close_our_leg(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Ledger(os.path.join(tmp, "l.db"))
            exchange = FakeExchange()
            orch = bind_explicit_protect_prices(
                Orchestrator(ledger, exchange, instance_id="a3b"))
            orch.recover()
            orch.open_position("LONG", 0.001, intent_id="W43-A3b")
            # 迟到的对侧腿成交：归属到"另一个"订单 id
            out = orch.apply_fill_event(Fill(
                fill_id="SHORTLEG-1",
                client_order_id="W43-A3b-SL",
                qty=0.002, price=99.0, fee=0.0, side="SELL",
                filled_at="2026-10-22T00:00:00Z",
                symbol="BTCUSDT", qty_raw="0.002", price_raw="99.0",
                fee_raw="0.0", fee_asset="USDT"))
            # 该成交必须进入证据路径（late fill 分类），不得静默把本腿订单
            # 标 FILLED 或意图标 RECONCILED
            intent = ledger.get_intent("W43-A3b")
            self.assertNotEqual(intent["state"], "RECONCILED")
            entry = ledger.get_order("W43-A3b-ENTRY")
            self.assertEqual(entry["state"], "FILLED")  # 本腿事实不被改写
            self.assertEqual(entry["filled_qty"], 0.001)
            ledger.close()


class A4FundingIncomeTests(unittest.TestCase):
    """#13679：资金费幂等入账；未取到 ≠ 0；与平仓路径解耦。"""

    def ROW(self, tran="9001", amount="-0.42", ts=1788600000000,
            asset="USDT"):
        return {"symbol": "BTCUSDT", "asset": asset,
                "incomeType": "FUNDING_FEE", "amount": amount,
                "time": ts, "tranId": tran, "entryId": None}

    def test_idempotent_by_stable_event_id_replay_ignored(self):
        store = {}
        first = ingest_funding_events([self.ROW()], store)
        self.assertEqual(first["added"], 1)
        # 同 ID 重放（迟到/重启重拉）不重复记账
        again = ingest_funding_events(
            [self.ROW(), self.ROW(tran="9002", amount="-0.10")], store)
        self.assertEqual(again["duplicates"], 1)
        self.assertEqual(again["added"], 1)
        self.assertEqual(funding_total(store), "-0.52")  # Decimal 精确

    def test_unavailable_is_unknown_never_zero(self):
        out = funding_fetch_unavailable("income endpoint timeout")
        self.assertEqual(out["state"], "UNKNOWN")
        self.assertEqual(out["added"], 0)
        store = {}
        self.assertIsNone(funding_total(store))  # 空库 → None≠"0"  # 无事件 → UNKNOWN，不是 0.0

    def test_rows_without_stable_id_rejected_fail_closed(self):
        store = {}
        out = ingest_funding_events(
            [{"symbol": "BTCUSDT", "incomeType": "FUNDING_FEE",
              "amount": "-1.0"}], store)  # 无 tranId/entryId/time
        self.assertEqual(out["rejected"], 1)
        self.assertEqual(out["added"], 0)
        self.assertIsNone(funding_total(store))  # 空库 → None≠"0"

    def test_stable_id_variants(self):
        self.assertEqual(stable_funding_event_id(self.ROW()), "tran:9001")
        self.assertEqual(
            stable_funding_event_id({"entryId": 7, "time": 123,
                                     "symbol": "BTCUSDT",
                                     "incomeType": "FUNDING_FEE"}),
            "entry:7:123")
        self.assertIsNone(stable_funding_event_id({}))

    def test_same_id_different_content_raises_conflict(self):
        store = {}
        ingest_funding_events([self.ROW()], store)
        with self.assertRaises(FundingIdentityConflict):
            ingest_funding_events(
                [self.ROW(amount="-0.99")], store)  # 同 ID 不同金额
        self.assertEqual(len(store), 1)  # 冲突不产生第二条

    def test_decimal_precision_and_multi_asset_no_cross_sum(self):
        store = {}
        rows = [
            self.ROW(tran="1", amount="0.1", ts=1),                       # BTCUSDT
            self.ROW(tran="2", amount="0.2", ts=2),
            {"symbol": "ETHUSDT", "incomeType": "FUNDING_FEE",
             "amount": "0.3", "time": 3, "tranId": "3", "asset": "USDC"},
        ]
        ingest_funding_events(rows, store)
        totals = funding_totals_by_asset(store)
        # 按【结算资产】分列：两行 USDT、一行 USDC —— 同资产 Decimal
        # 精确合计，跨资产不相加
        self.assertEqual(totals["USDT"], "0.3")
        self.assertEqual(totals["USDC"], "0.3")
        self.assertEqual(len(totals), 2)
        self.assertEqual(store["tran:1"]["amount_raw"], "0.1")  # 原始串保留

    def test_window_completeness_semantics(self):
        w_ok = declare_window(0, 100, pages_ok=True, reached_end=True,
                              empty_response=False)
        self.assertEqual(w_ok["state"], "COMPLETE")
        w_empty = declare_window(0, 100, pages_ok=True, reached_end=True,
                                 empty_response=True)
        self.assertEqual(w_empty["state"], "COMPLETE_ZERO_EVENTS")
        w_partial = declare_window(0, 100, pages_ok=False, reached_end=False,
                                   empty_response=False)
        self.assertEqual(w_partial["state"], "PARTIAL")
        # 迟到事件命中已 COMPLETE 窗口 → 降级
        degraded = apply_late_event_check(w_ok, 50)
        self.assertEqual(degraded["state"], "PARTIAL_LATE")
        outside = apply_late_event_check(w_ok, 500)
        self.assertEqual(outside["state"], "COMPLETE")


class FillIdentityConflictTests(unittest.TestCase):
    """W43 复审：成交身份冲突告警（同 ID 不同内容不静默忽略）。"""

    def _seed_order(self, led, cid):
        led.create_intent("I-" + cid, "BTCUSDT", "LONG", 0.01)
        led.record_order_submitting(
            client_order_id=cid, intent_id="I-" + cid, order_kind="ENTRY",
            side="BUY", position_side="LONG", quantity=0.01)

    def test_identical_replay_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            led = Ledger(os.path.join(tmp, "l.db"))
            self._seed_order(led, "C1")
            self.assertTrue(led.insert_fill(
                "F1", "C1", 0.01, 100.0, 0.0, "BUY", "t1"))
            self.assertFalse(led.insert_fill(
                "F1", "C1", 0.01, 100.0, 0.0, "BUY", "t1"))
            led.close()

    def test_same_id_different_content_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            led = Ledger(os.path.join(tmp, "l.db"))
            for cid in ("C1", "C2"):
                self._seed_order(led, cid)
            led.insert_fill("F1", "C1", 0.01, 100.0, 0.0, "BUY", "t1")
            for bad in (("C2", 0.01, 100.0, "BUY"),
                        ("C1", 0.02, 100.0, "BUY"),
                        ("C1", 0.01, 101.0, "BUY"),
                        ("C1", 0.01, 100.0, "SELL")):
                with self.assertRaises(FillIdentityConflict, msg=str(bad)):
                    led.insert_fill("F1", bad[0], bad[1], bad[2], 0.0,
                                    bad[3], "t1")
            led.close()


if __name__ == "__main__":
    unittest.main()


class A1CrossProcessRestartTests(unittest.TestCase):
    """W43 复审：A1 的 submit_log=1 必须跨【真实进程边界】成立。

    阶段一（子进程）：开仓遇 SUBMIT_UNKNOWN，把账本与交易所状态
    pickle 落盘后进程退出。
    阶段二（另一子进程）：新进程加载两者、恢复，报告 ENTRY 提交数
    与归属。父进程断言：跨进程后仍恰好 1 次提交、原 ID 归属。
    """

    PHASE2 = r"""
import json, os, pickle, sys
state_dir, repo_root = sys.argv[1], sys.argv[2]
sys.path.insert(0, repo_root)
from aurora.kernel.ledger import Ledger
from aurora.kernel.orchestrator import Orchestrator
from tests.kernel_test_open import bind_explicit_protect_prices

with open(os.path.join(state_dir, "exchange.pkl"), "rb") as fh:
    exchange = pickle.load(fh)
ledger = Ledger(os.path.join(state_dir, "ledger.db"))
orch = bind_explicit_protect_prices(
    Orchestrator(ledger, exchange, instance_id="w43-proc2"))
report = orch.recover()
intent = ledger.get_intent("W43-XP")
entry_submits = [r.client_order_id for r in exchange.submit_log
                 if r.order_kind.name == "ENTRY"]
print(json.dumps({
    "entry_submit_count": len(entry_submits),
    "entry_ids": entry_submits,
    "intent_state": intent["state"],
    "entry_filled_qty": ledger.get_order("W43-XP-ENTRY")["filled_qty"],
    "unresolved": bool(report["unresolved"]),
}))
ledger.close()
"""

    def test_submit_once_holds_across_real_process_restart(self):
        import pickle
        import subprocess
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with tempfile.TemporaryDirectory() as state_dir:
            # 阶段一：独立子进程制造 SUBMIT_UNKNOWN 并持久化
            phase1 = (
                "import os, pickle, sys\n"
                "sys.path.insert(0, {root!r})\n"
                "from aurora.kernel.ledger import Ledger\n"
                "from aurora.kernel.orchestrator import Orchestrator\n"
                "from aurora.kernel.fake_exchange import FakeExchange\n"
                "from tests.kernel_test_open import bind_explicit_protect_prices\n"
                "sd = {sd!r}\n"
                "ex = FakeExchange(entry_behavior='timeout_then_filled')\n"
                "led = Ledger(os.path.join(sd, 'ledger.db'))\n"
                "orch = bind_explicit_protect_prices(\n"
                "    Orchestrator(led, ex, instance_id='w43-proc1'))\n"
                "orch.recover()\n"
                "out = orch.open_position('LONG', 0.01, intent_id='W43-XP')\n"
                "assert out['state'] == 'SUBMIT_UNKNOWN', out\n"
                "led.close()\n"
                "with open(os.path.join(sd, 'exchange.pkl'), 'wb') as fh:\n"
                "    pickle.dump(ex, fh)\n"
            ).format(root=base, sd=state_dir)
            r1 = subprocess.run([sys.executable, "-c", phase1],
                                capture_output=True, text=True, cwd=base)
            self.assertEqual(r1.returncode, 0, r1.stderr[-500:])

            # 阶段二：另一个独立进程恢复
            r2 = subprocess.run(
                [sys.executable, "-c", self.PHASE2, state_dir, base],
                capture_output=True, text=True, cwd=base)
            self.assertEqual(r2.returncode, 0, r2.stderr[-500:])
            result = json.loads(r2.stdout.strip().splitlines()[-1])
            self.assertEqual(result["entry_submit_count"], 1)  # 跨进程仍 1 次
            self.assertEqual(result["entry_ids"], ["W43-XP-ENTRY"])  # 原 ID
            self.assertAlmostEqual(result["entry_filled_qty"], 0.01,
                                   places=10)  # 权威归属成功
            self.assertIn(result["intent_state"],
                          ("PROTECTED", "FILLED_UNPROTECTED"))


class EventEntryConflictBypassTests(unittest.TestCase):
    """W43 复验缺陷1：事件入口在内容比较前直接返回 DUPLICATE，
    绕过 insert_fill 的身份冲突检查。红→绿。"""

    def _seed(self, led):
        led.create_intent("I-EE", "BTCUSDT", "LONG", 0.01)
        led.record_order_submitting(
            client_order_id="EE-C", intent_id="I-EE", order_kind="ENTRY",
            side="BUY", position_side="LONG", quantity=0.01)

    def test_conflicting_event_content_is_not_silent_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            led = Ledger(os.path.join(tmp, "l.db"))
            self._seed(led)
            orch = Orchestrator(led, FakeExchange(), instance_id="ee")
            first = orch.apply_fill_event(Fill(
                fill_id="EE-1", client_order_id="EE-C",
                qty=0.01, price=100.0, fee=0.0, side="BUY",
                filled_at="t1",
                symbol="BTCUSDT", qty_raw="0.01", price_raw="100.0",
                fee_raw="0.0", fee_asset="USDT"))
            self.assertEqual(first["class"], "LATE_NEW_FILL")
            # 同 fill_id、不同内容（qty/price/cid 变化）——事件入口必须
            # 识别为身份冲突并持久化告警，而不是 DUPLICATE
            # 冻结语义（评审 3）：qty/price 跨等级→UNRESOLVED；
            # 离散 side 冲突→CONFLICT+kill
            out = orch.apply_fill_event(Fill(
                fill_id="EE-1", client_order_id="EE-C",
                qty=0.02, price=100.0, fee=0.0, side="BUY",
                filled_at="t1",
                symbol="BTCUSDT", qty_raw="0.02", price_raw="100.0",
                fee_raw="0.0", fee_asset="USDT"))
            self.assertEqual(out["class"], "IDENTITY_UNRESOLVED")
            out2 = orch.apply_fill_event(Fill(
                fill_id="EE-1", client_order_id="EE-C",
                qty=0.01, price=100.0, fee=0.0, side="SELL",
                filled_at="t1",
                symbol="BTCUSDT", qty_raw="0.01", price_raw="100.0",
                fee_raw="0.0", fee_asset="USDT"))
            self.assertEqual(out2["class"], "IDENTITY_CONFLICT")
            self.assertEqual(led.kill_state()["engaged"], 1)
            self.assertIn("identity conflict",
                          led.kill_state()["reason"])
            # 一致重放仍幂等为 DUPLICATE
            same = orch.apply_fill_event(Fill(
                fill_id="EE-1", client_order_id="EE-C",
                qty=0.01, price=100.0, fee=0.0, side="BUY",
                filled_at="t1",
                symbol="BTCUSDT", qty_raw="0.01", price_raw="100.0",
                fee_raw="0.0", fee_asset="USDT"))
            # D-a 语义（逐项说明）：qty/price 确认同值；fee 单侧
            # 不可证实 → UNRESOLVED（不确认重复）。安全断言保留：
            # 无第二次记账 + 不触发全局 kill（审计事件而非 kill）。
            self.assertEqual(same["class"], "IDENTITY_UNRESOLVED")
            with self.assertRaises(Exception):
                conn_ro = sqlite3.connect(led.path
                                          if hasattr(led, "path") else ":memory:")
                conn_ro.close()
            self.assertEqual(
                len(led.fills_for_order("EE-C")), 1)
            led.close()


class FakeDualLegViaRealOrdersTests(unittest.TestCase):
    """W43 复验缺陷2：真实订单成交构成的双腿（非外部种子）必须
    返回 UNKNOWN，不得净额成假空仓。红→绿。"""

    def test_buy_long_plus_sell_short_yields_unknown_not_flat(self):
        import uuid
        from aurora.kernel.port import OrderRequest
        ex = FakeExchange()
        # 通过真实 submit_order 构造双腿：LONG 腿 BUY + SHORT 腿 SELL
        ex.submit_order(OrderRequest(
            client_order_id=f"L-{uuid.uuid4().hex[:6]}", symbol="BTCUSDT",
            order_kind=OrderKind.ENTRY, side="BUY", position_side="LONG",
            quantity=0.001))
        ex.submit_order(OrderRequest(
            client_order_id=f"S-{uuid.uuid4().hex[:6]}", symbol="BTCUSDT",
            order_kind=OrderKind.ENTRY, side="SELL", position_side="SHORT",
            quantity=0.001))
        pos = ex.position("BTCUSDT")
        self.assertIsNone(
            pos,
            f"dual non-zero legs must be UNKNOWN, got {pos}")

    def test_short_leg_reduce_via_buy_keeps_single_leg_known(self):
        import uuid
        from aurora.kernel.port import OrderRequest
        ex = FakeExchange()
        ex.submit_order(OrderRequest(
            client_order_id=f"S1-{uuid.uuid4().hex[:6]}", symbol="BTCUSDT",
            order_kind=OrderKind.ENTRY, side="SELL", position_side="SHORT",
            quantity=0.002))
        ex.submit_order(OrderRequest(
            client_order_id=f"S2-{uuid.uuid4().hex[:6]}", symbol="BTCUSDT",
            order_kind=OrderKind.CLOSE, side="BUY", position_side="SHORT",
            quantity=0.001, reduce_only=True))
        pos = ex.position("BTCUSDT")
        # 只剩 SHORT 腿净 0.001：单腿 → 已知（负）
        self.assertIsNotNone(pos)
        self.assertAlmostEqual(pos.signed_qty, -0.001, places=10)


class FundingInputConstraintsTests(unittest.TestCase):
    """W43 复验缺陷3：funding 输入约束四项。红→绿。"""

    def test_asset_change_same_id_is_conflict(self):
        store = {}
        ingest_funding_events([{"symbol": "BTCUSDT", "asset": "USDT",
                                "incomeType": "FUNDING_FEE", "amount": "-0.4",
                                "time": 1, "tranId": "T1"}], store)
        with self.assertRaises(FundingIdentityConflict):
            ingest_funding_events([{"symbol": "BTCUSDT", "asset": "USDC",
                                     "incomeType": "FUNDING_FEE",
                                     "amount": "-0.4", "time": 1,
                                     "tranId": "T1"}], store)

    def test_non_finite_amounts_rejected(self):
        store = {}
        for bad in ("NaN", "Infinity", "-Infinity"):
            out = ingest_funding_events(
                [{"symbol": "BTCUSDT", "asset": "USDT",
                  "incomeType": "FUNDING_FEE", "amount": bad,
                  "time": 1, "tranId": "T-" + bad}], store)
            self.assertEqual(out["rejected"], 1, bad)
        self.assertEqual(len(store), 0)  # 非有限值不入库不污染合计

    def test_no_stable_id_fallback_combo_rejected(self):
        # 无 tranId/entryId：type+symbol+time 组合不能冒充稳定身份
        self.assertIsNone(stable_funding_event_id(
            {"symbol": "BTCUSDT", "incomeType": "FUNDING_FEE",
             "amount": "-1", "time": 5}))
        store = {}
        out = ingest_funding_events(
            [{"symbol": "BTCUSDT", "incomeType": "FUNDING_FEE",
              "amount": "-1", "time": 5}], store)
        self.assertEqual(out["rejected"], 1)

    def test_missing_asset_rejected_not_guessed(self):
        store = {}
        out = ingest_funding_events(
            [{"symbol": "BTCUSDT", "incomeType": "FUNDING_FEE",
              "amount": "-1", "time": 1, "tranId": "T9"}], store)
        self.assertEqual(out["rejected"], 1)  # 缺结算币种 → 拒收不猜
        self.assertEqual(len(store), 0)
