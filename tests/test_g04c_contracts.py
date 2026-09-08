"""G0-4C 保护生命周期恢复合同（离线 / FakeExchange，零出网）。

C1 FILLED_UNPROTECTED 可恢复：重启 + 有仓 → 进入保护恢复，不被忽略。
C2 保护腿不重复提交：SUBMIT_UNKNOWN + 重启 ≠ 第二次提交；
   只有权威"确认不存在"证据才允许重提。
C3 覆盖按实际仓位核对：PARTIAL 不得宣称 VERIFIED；
   COVERAGE_OVERFLOW 是危险合同 → 降级重建。
C4 仓位缩减后旧保护失配 → 撤旧重建，不保持 VERIFIED。
C5 TRIGGERED/FINISHED ≠ FILLED：无 actualOrderId/权威成交 → unresolved；
   有权威成交 + 仓位归零 → 才允许收敛。
C6 FLAT + ACTIVE 保护残留 → ORPHAN_PROTECTION fail-closed，不普通 RECONCILED。
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hypothesis import given, settings, strategies as st  # noqa: E402

from tests.kernel_test_open import bind_explicit_protect_prices  # noqa: E402
from aurora.kernel.coverage import compute_protection_status  # noqa: E402
from aurora.kernel.fake_exchange import FakeExchange  # noqa: E402
from aurora.kernel.ledger import (  # noqa: E402
    CLOSE_PROVENANCE_UNKNOWN, Ledger, PositionFactState,
)
from aurora.kernel.orchestrator import Orchestrator  # noqa: E402
from aurora.kernel.port import OrderKind, OrderRequest  # noqa: E402
from aurora.kernel.state_machine import IntentState  # noqa: E402


class LifecycleHarness(unittest.TestCase):
    def tearDown(self):
        if getattr(self, "ledger", None):
            self.ledger.close()
        if getattr(self, "_tmp", None):
            self._tmp.cleanup()

    def _boot(self, entry="ok", protection="ok", close="ok"):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "ledger.db")
        self.exchange = FakeExchange(
            entry_behavior=entry, protection_behavior=protection,
            close_behavior=close)
        self.ledger = Ledger(self.path)
        self.orch = bind_explicit_protect_prices(
            Orchestrator(self.ledger, self.exchange, instance_id="g04c"))
        self.orch.recover()
        return self.orch

    def _craft_filled_unprotected(self, iid, qty, price=100.0,
                                  with_active_sl=False, sl_qty=None,
                                  mid_state="FILLED_UNPROTECTED"):
        """构造"入场已成交、保护未挂/部分挂"的崩溃遗留形态。"""
        self.ledger.create_intent(iid, "BTCUSDT", "LONG", qty)
        self.ledger.claim_intent(iid, "craft")
        self.ledger.transition_intent(
            iid, IntentState.SUBMITTING, "craft: entry submit")
        if mid_state == "PARTIALLY_FILLED":
            self.ledger.transition_intent(
                iid, IntentState.PARTIALLY_FILLED, "craft: partial fill")
        else:
            self.ledger.transition_intent(
                iid, IntentState.FILLED_UNPROTECTED,
                "craft: entry filled; crash before protection")
            if mid_state == "PROTECTION_SUBMITTING":
                self.ledger.transition_intent(
                    iid, IntentState.PROTECTION_SUBMITTING,
                    "craft: crash during protection submit")
        cid = f"{iid}-ENTRY"
        self.ledger.record_order_submitting(
            client_order_id=cid, intent_id=iid, order_kind="ENTRY",
            side="BUY", position_side="LONG", quantity=qty)
        self.ledger.update_order(
            cid, state="FILLED", filled_qty=qty, avg_price=price)
        self.ledger.insert_fill(f"{iid}-F1", cid, qty, price, 0.0, "BUY", "craft")
        # G0-4B 合同：开仓时计划价已持久化（真实流程经 open_position 落库）
        self.ledger.set_intent_protect_prices(iid, 99.0, 101.0)
        self.exchange.seed_external_position(qty, price)
        if with_active_sl:
            live_qty = sl_qty if sl_qty is not None else qty
            scid = f"{iid}-SL"
            self.ledger.record_order_submitting(
                client_order_id=scid, intent_id=iid, order_kind="STOP_LOSS",
                side="SELL", position_side="LONG", quantity=live_qty,
                stop_price=99.0, reduce_only=True)
            self.ledger.update_order(scid, state="ACTIVE")
            # 存量腿直接注册到交易所态（构造语义：崩溃前已挂上）；
            # behavior 旋钮只约束恢复期的新提交，不管构造。
            req = OrderRequest(
                client_order_id=scid, symbol="BTCUSDT",
                order_kind=OrderKind.STOP_LOSS, side="SELL",
                position_side="LONG", quantity=live_qty, stop_price=99.0,
                reduce_only=True)
            self.exchange.submit_log.append(req)
            self.exchange._orders[scid] = {
                "req": req, "status": "NEW", "filled_qty": 0.0, "avg_price": 0.0,
            }

    def _restart(self, instance="g04c-restart"):
        self.ledger.close()
        self.ledger = Ledger(self.path)
        self.orch = bind_explicit_protect_prices(
            Orchestrator(self.ledger, self.exchange, instance_id=instance))
        return self.orch

    def _sl_submissions(self):
        return [r for r in self.exchange.submit_log
                if r.order_kind == OrderKind.STOP_LOSS]


class ProtectionRecoveryTests(LifecycleHarness):
    def test_M1_filled_unprotected_restarts_into_protection_recovery(self):
        self._boot()
        self._craft_filled_unprotected("C1", 0.007)
        self._restart("g04c-C1-restart")
        report = self.orch.recover()
        intent = self.ledger.get_intent("C1")
        self.assertEqual(intent["state"], IntentState.PROTECTED.value)
        sl = self._sl_submissions()
        self.assertEqual(len(sl), 1)
        self.assertAlmostEqual(sl[0].quantity, 0.007, places=10)
        self.assertNotAlmostEqual(sl[0].quantity, 0.0, places=10)
        self.assertFalse(any(
            e.get("fact") == "PROTECTION_RECOVERY" for e in report["unresolved"]))

    def test_M2_sl_submit_unknown_restart_never_resubmits(self):
        self._boot(protection="timeout_then_filled")
        result = self.orch.open_position(
            "LONG", 0.01, intent_id="C2")
        self.assertEqual(result["state"], "RECOVERY_REQUIRED")
        self.assertEqual(len(self._sl_submissions()), 1)
        # 重启（新内核实例，同一账本/交易所）
        self._restart("g04c-B")
        for _ in range(3):
            self.orch.recover()
        self.assertEqual(len(self._sl_submissions()), 1)

    def test_M3_existing_active_algo_recognized_no_resubmit(self):
        self._boot()
        self._craft_filled_unprotected("C3", 0.007, with_active_sl=True, sl_qty=0.007)
        report = self.orch.recover()
        self.assertEqual(
            self.ledger.get_intent("C3")["state"], IntentState.PROTECTED.value)
        self.assertEqual(len(self._sl_submissions()), 1)  # 无第二次提交
        self.assertFalse(any(
            e.get("fact") == "PROTECTION_RECOVERY" for e in report["unresolved"]))

    def test_M4_partial_coverage_topped_up_not_claimed_early(self):
        self._boot()
        self._craft_filled_unprotected("C4", 0.007, with_active_sl=True, sl_qty=0.005)
        before = compute_protection_status(
            self.ledger.orders_for_intent("C4"), 0.007)
        self.assertAlmostEqual(before.sl_coverage, 0.005, places=10)
        self.assertFalse(before.protected_full)  # PARTIAL 不能提前 VERIFIED
        report = self.orch.recover()
        self.assertEqual(
            self.ledger.get_intent("C4")["state"], IntentState.PROTECTED.value)
        sl = self._sl_submissions()
        self.assertEqual(len(sl), 2)  # 原腿 0.005 + 差额补齐 0.002
        self.assertAlmostEqual(sl[1].quantity, 0.002, places=10)
        self.assertFalse(any(
            e.get("fact") == "PROTECTION_RECOVERY" for e in report["unresolved"]))

    def test_M4b_partial_with_rejected_topup_never_verified(self):
        self._boot(protection="reject")
        self._craft_filled_unprotected("C4b", 0.007, with_active_sl=True, sl_qty=0.005)
        report = self.orch.recover()
        state = self.ledger.get_intent("C4b")["state"]
        self.assertNotEqual(state, IntentState.PROTECTED.value)
        self.assertTrue(report["unresolved"] or self.ledger.kill_state()["engaged"])

    def test_M5_coverage_overflow_rebuilds_at_position(self):
        self._boot()
        self._craft_filled_unprotected("C5ov", 0.007, with_active_sl=True, sl_qty=0.010)
        report = self.orch.recover()
        self.assertEqual(
            self.ledger.get_intent("C5ov")["state"], IntentState.PROTECTED.value)
        old = self.ledger.get_order("C5ov-SL")
        self.assertEqual(old["state"], "CANCELLED")
        sl = self._sl_submissions()
        self.assertEqual(len(sl), 2)
        self.assertAlmostEqual(sl[1].quantity, 0.007, places=10)  # 按实际仓位重建
        self.assertFalse(self.ledger.kill_state()["engaged"])

    def test_M6_position_reduction_rebuilds_protection(self):
        self._boot()
        self.orch.open_position("LONG", 0.007, intent_id="C6red")
        self.exchange.seed_external_position(-0.002, 100.0)  # 外部/手工减仓
        report = self.orch.recover()
        self.assertEqual(
            self.ledger.get_intent("C6red")["state"], IntentState.PROTECTED.value)
        old = self.ledger.get_order("C6red-SL")
        self.assertEqual(old["state"], "CANCELLED")
        sl = self._sl_submissions()
        self.assertEqual(len(sl), 2)
        self.assertAlmostEqual(sl[1].quantity, 0.005, places=10)

    def test_M7_triggered_without_authoritative_fill_stays_unresolved(self):
        self._boot()
        self.orch.open_position("LONG", 0.01, intent_id="C7")
        self.exchange.mark_algo_triggered("C7-SL")  # TRIGGERED，无成交
        report = self.orch.recover()
        self.assertTrue(report["unresolved"])
        self.assertEqual(self.ledger.fills_for_order("C7-SL"), [])
        self.assertNotEqual(
            self.ledger.get_intent("C7")["state"], IntentState.RECONCILED.value)
        self.assertEqual(
            self.ledger.get_position_fact("BTCUSDT")["state"],
            PositionFactState.UNKNOWN.value)

    def test_M8_triggered_with_authoritative_fill_and_flat_converges(self):
        self._boot()
        self.orch.open_position("LONG", 0.01, intent_id="C8")
        self.exchange.mark_algo_triggered("C8-SL")
        self.exchange.fire_protection("C8-SL", price=99.0)  # 权威成交到达
        report = self.orch.recover()
        self.assertEqual(
            self.ledger.get_intent("C8")["state"], IntentState.RECONCILED.value)
        self.assertEqual(len(self.ledger.fills_for_order("C8-SL")), 1)
        self.assertEqual(report["unresolved"], [])

    def test_M9_sl_fired_full_and_flat_reconciles(self):
        self._boot()
        self.orch.open_position("LONG", 0.01, intent_id="C9")
        self.exchange.fire_protection("C9-SL", price=98.0)
        report = self.orch.recover()
        self.assertEqual(
            self.ledger.get_intent("C9")["state"], IntentState.RECONCILED.value)
        self.assertEqual(report["unresolved"], [])

    def test_M10_flat_with_active_protection_is_orphan_fail_closed(self):
        self._boot()
        self._craft_filled_unprotected("C10", 0.007, with_active_sl=True, sl_qty=0.007)
        # 交易所在无任何平仓证据的情况下变为空仓（外部动作/手工平仓）
        self.exchange.flatten_without_fill()
        report = self.orch.recover()
        facts = [e.get("fact") for e in report["unresolved"]]
        self.assertIn("ORPHAN_PROTECTION", facts)
        self.assertTrue(self.ledger.kill_state()["engaged"])
        refused = self.orch.open_position(
            "LONG", 0.007, intent_id="C10-new")
        self.assertFalse(refused["success"])  # fail closed：新风险被熔断阻断

    def test_M11_protection_query_failure_is_unknown_never_none(self):
        self._boot()
        self.orch.open_position("LONG", 0.01, intent_id="C11")
        self.exchange.fail_order_queries(True)
        report = self.orch.recover()
        self.assertTrue(report["unresolved"])
        self.assertEqual(
            self.ledger.get_position_fact("BTCUSDT")["state"],
            PositionFactState.UNKNOWN.value)  # 不是 KNOWN_FLAT/无保护

    def test_M12_repeated_recover_idempotent(self):
        self._boot()
        self._craft_filled_unprotected("C12", 0.007, with_active_sl=True, sl_qty=0.007)
        fills = lambda: sum(len(self.ledger.fills_for_order(o))
                            for o in ("C12-ENTRY", "C12-SL"))
        for i in range(5):
            if i in (1, 3):
                self._restart(f"g04c-C12-restart-{i}")
            report = self.orch.recover()
            self.assertEqual(
                self.ledger.get_intent("C12")["state"],
                IntentState.PROTECTED.value, f"round {i}")
            self.assertEqual(len(self._sl_submissions()), 1, f"round {i}")
            self.assertEqual(fills(), 1, f"round {i}")
            self.assertFalse(self.ledger.kill_state()["engaged"], f"round {i}")

    def test_M13_protection_submitting_restart_recognizes_active_sl(self):
        self._boot()
        self._craft_filled_unprotected(
            "C13", 0.007, with_active_sl=True, sl_qty=0.007,
            mid_state="PROTECTION_SUBMITTING")
        self._restart("g04c-C13")
        report = self.orch.recover()
        self.assertEqual(
            self.ledger.get_intent("C13")["state"], IntentState.PROTECTED.value)
        self.assertEqual(len(self._sl_submissions()), 1)
        self.assertFalse(any(
            e.get("fact") == "PROTECTION_RECOVERY" for e in report["unresolved"]))

    def test_M14_unprotected_flat_is_close_provenance_unknown(self):
        self._boot()
        self._craft_filled_unprotected("C14", 0.007)
        self.exchange.flatten_without_fill()
        report = self.orch.recover()
        facts = [e.get("fact") for e in report["unresolved"]]
        self.assertIn(CLOSE_PROVENANCE_UNKNOWN, facts)
        self.assertEqual(
            self.ledger.get_intent("C14")["state"],
            IntentState.RECOVERY_REQUIRED.value)
        self.assertNotEqual(
            self.ledger.get_intent("C14")["state"],
            IntentState.RECONCILED.value)
        self.assertEqual(
            self.ledger.get_position_fact("BTCUSDT")["source"],
            CLOSE_PROVENANCE_UNKNOWN)
        sells = []
        for order in self.ledger.orders_for_intent("C14"):
            sells.extend(
                f for f in self.ledger.fills_for_order(order["client_order_id"])
                if f["side"] == "SELL")
        self.assertEqual(sells, [])

    def test_M15_repair_flatten_without_fill_is_provenance_not_reconciled(self):
        self._boot()
        self._craft_filled_unprotected(
            "C15", 0.007, with_active_sl=True, sl_qty=0.010)
        self.exchange.flatten_on_cancel = True
        report = self.orch.recover()
        self.assertNotEqual(
            self.ledger.get_intent("C15")["state"],
            IntentState.RECONCILED.value)
        self.assertEqual(
            self.ledger.get_intent("C15")["state"],
            IntentState.RECOVERY_REQUIRED.value)
        self.assertEqual(
            self.ledger.get_position_fact("BTCUSDT")["source"],
            CLOSE_PROVENANCE_UNKNOWN)
        self.assertTrue(
            any(e.get("fact") in (CLOSE_PROVENANCE_UNKNOWN, "ORPHAN_PROTECTION")
                for e in report["unresolved"]))
        self.assertEqual(self.ledger.fills_for_order("C15-SL"), [])

    def test_M16_repair_position_change_rebuilds_at_live_qty(self):
        self._boot()
        self._craft_filled_unprotected(
            "C16", 0.007, with_active_sl=True, sl_qty=0.010)
        self.exchange.position_delta_on_cancel = -0.003
        report = self.orch.recover()
        self.assertEqual(
            self.ledger.get_intent("C16")["state"], IntentState.PROTECTED.value)
        sl = self._sl_submissions()
        self.assertEqual(len(sl), 2)
        self.assertAlmostEqual(sl[1].quantity, 0.004, places=10)
        self.assertFalse(self.ledger.kill_state()["engaged"])
        self.assertFalse(any(
            e.get("fact") == "PROTECTION_RECOVERY" for e in report["unresolved"]))


class LifecyclePropertyTests(LifecycleHarness):
    @given(
        qty=st.floats(min_value=0.002, max_value=0.02),
        fraction=st.floats(min_value=0.1, max_value=0.9),
    )
    @settings(max_examples=15, deadline=None)
    def test_P1_partial_coverage_never_verified(self, qty, fraction):
        self._boot(protection="reject")
        self._craft_filled_unprotected(
            "P1", round(qty, 6), with_active_sl=True,
            sl_qty=round(qty * fraction, 6))
        self.orch.recover()
        self.assertNotEqual(
            self.ledger.get_intent("P1")["state"], IntentState.PROTECTED.value)

    @given(rounds=st.integers(min_value=1, max_value=6))
    @settings(max_examples=8, deadline=None)
    def test_P2_submit_unknown_no_resubmit_in_any_rounds(self, rounds):
        self._boot(protection="timeout_then_filled")
        self.orch.open_position("LONG", 0.01, intent_id="P2")
        self.exchange.fail_order_queries(True)  # 无权威证据：查不到事实
        self.ledger.close()
        self.ledger = Ledger(self.path)
        self.orch = bind_explicit_protect_prices(
            Orchestrator(self.ledger, self.exchange, instance_id="P2-B"))
        for _ in range(rounds):
            report = self.orch.recover()
            self.assertTrue(report["unresolved"])
        self.assertEqual(len(self._sl_submissions()), 1)

    @given(qty=st.floats(min_value=0.002, max_value=0.02))
    @settings(max_examples=10, deadline=None)
    def test_P3_orphan_protection_blocks_clean_reconcile(self, qty):
        self._boot()
        self._craft_filled_unprotected(
            "P3", round(qty, 6), with_active_sl=True, sl_qty=round(qty, 6))
        self.exchange.flatten_without_fill()
        report = self.orch.recover()
        self.assertIn(
            "ORPHAN_PROTECTION", [e.get("fact") for e in report["unresolved"]])
        self.assertNotEqual(
            self.ledger.get_intent("P3")["state"], IntentState.RECONCILED.value)


if __name__ == "__main__":
    unittest.main()
