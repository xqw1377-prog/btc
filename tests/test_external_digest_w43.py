"""外部周报 2026-W43 吸收：四项上游缺陷 → 离线测试与状态机约束。

来源（不构成交易依赖升级理由，全部离线吸收）：
A1 NautilusTrader #5375 — 未知提交跨重启丢失订单归属
A2 NautilusTrader #5377 — 用户流恢复在 -1125 类凭证失效上无限卡死
A3 NautilusTrader #5416 — Hedge Mode 下错误仓位快照"覆盖"成交
A4 Freqtrade #13679 — 交易所止损平仓路径漏记资金费
"""
import os
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
    funding_fetch_unavailable,
    funding_total,
    ingest_funding_events,
    stable_funding_event_id,
)
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
            filled_at="2026-10-20T00:00:00Z"))
        self.assertEqual(out["class"], "ORPHAN")
        self.assertEqual(ledger.kill_state()["engaged"], 1)
        # 该成交不得被并入我们的意图；无新 ENTRY 铸造
        self.assertEqual(ledger.fills_for_order("NOT-OURS-XYZ"), [])
        entry_submits = [r for r in exchange.submit_log
                         if r.order_kind == OrderKind.ENTRY]
        self.assertEqual(len(entry_submits), 1)
        ledger.close()


class A2StaleCredentialNeverThrottledTests(unittest.TestCase):
    """#5377 的 REST 等价约束：凭证失效类错误不得被当瞬态限流重试。"""

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
                client_order_id="W43-A3b-SL",  # 同意图的 SL 腿 id 冒充
                qty=0.002, price=99.0, fee=0.0, side="SELL",
                filled_at="2026-10-22T00:00:00Z"))
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

    def ROW(self, tran="9001", amount="-0.42", ts=1788600000000):
        return {"symbol": "BTCUSDT", "incomeType": "FUNDING_FEE",
                "amount": amount, "time": ts, "tranId": tran,
                "entryId": None}

    def test_idempotent_by_stable_event_id_replay_ignored(self):
        store = {}
        first = ingest_funding_events([self.ROW()], store)
        self.assertEqual(first["added"], 1)
        # 同 ID 重放（迟到/重启重拉）不重复记账
        again = ingest_funding_events(
            [self.ROW(), self.ROW(tran="9002", amount="-0.10")], store)
        self.assertEqual(again["duplicates"], 1)
        self.assertEqual(again["added"], 1)
        self.assertAlmostEqual(funding_total(store), -0.52, places=10)

    def test_unavailable_is_unknown_never_zero(self):
        out = funding_fetch_unavailable("income endpoint timeout")
        self.assertEqual(out["state"], "UNKNOWN")
        self.assertEqual(out["added"], 0)
        store = {}
        self.assertIsNone(funding_total(store))  # 无事件 → UNKNOWN，不是 0.0

    def test_rows_without_stable_id_rejected_fail_closed(self):
        store = {}
        out = ingest_funding_events(
            [{"symbol": "BTCUSDT", "incomeType": "FUNDING_FEE",
              "amount": "-1.0"}], store)  # 无 tranId/entryId/time
        self.assertEqual(out["rejected"], 1)
        self.assertEqual(out["added"], 0)
        self.assertIsNone(funding_total(store))

    def test_stable_id_variants(self):
        self.assertEqual(stable_funding_event_id(self.ROW()), "tran:9001")
        self.assertEqual(
            stable_funding_event_id({"entryId": 7, "time": 123,
                                     "symbol": "BTCUSDT",
                                     "incomeType": "FUNDING_FEE"}),
            "entry:7:123")
        self.assertIsNone(stable_funding_event_id({}))


if __name__ == "__main__":
    unittest.main()
