"""P0-B2 性质测试：随机事件序列下的内核不变量（Hypothesis）。

吸收建议（NautilusTrader/Hummingbot 踩坑清单）转化为可随机验证的不变量：
I1 幂等：同一 Intent 永远最多一个 ENTRY 提交；
I2 熔断单调：Kill Switch 一旦触发，场景内任何路径不会自动解除；
I3 事实收敛：恢复后，账本订单成交量 == 交易所查询事实；
I4 持仓一致：恢复后，持仓事实与交易所事实一致（含 UNKNOWN）；
I5 状态合法：所有意图状态都在 15 态状态机内，且转移经由校验。
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from aurora.kernel.fake_exchange import FakeExchange  # noqa: E402
from aurora.kernel.ledger import Ledger, PositionFactState  # noqa: E402
from aurora.kernel.orchestrator import Orchestrator  # noqa: E402
from aurora.kernel.port import OrderKind  # noqa: E402
from aurora.kernel.state_machine import IntentState  # noqa: E402
from tests.kernel_test_open import bind_explicit_protect_prices  # noqa: E402

try:
    from test_protection_semantics import oracle_coverage  # noqa: E402
except ImportError:  # tests/ 存在 __init__.py 时按包导入
    from tests.test_protection_semantics import oracle_coverage  # noqa: E402

BEHAVIORS = st.sampled_from(
    ["ok", "reject", "timeout_then_filled", "timeout_then_gone", "partial"])
OPS = st.sampled_from(
    ["open", "fire_sl", "fire_tp", "complete_entry", "close", "restart_recover"])


class KernelPropertyTests(unittest.TestCase):
    def _assert_invariants(self, orch, exchange, ledger, seen_kill):
        # I1 幂等
        entries = [r for r in exchange.submit_log if r.order_kind == OrderKind.ENTRY]
        self.assertLessEqual(len(entries), 1, "duplicate ENTRY submission")
        # I2 熔断单调：一旦观测到 kill，场景内不得自动解除
        kill_now = bool(ledger.kill_state()["engaged"])
        if seen_kill:
            self.assertTrue(kill_now, "kill switch cleared spontaneously")
        # I5 状态合法
        for intent in ledger.list_intents():
            self.assertIn(intent["state"], [s.value for s in IntentState])
        return kill_now

    def _assert_convergence(self, orch, exchange, ledger):
        report = orch.recover()
        # I3 事实收敛：FILLED 订单账本成交量 == 交易所事实
        for intent in ledger.list_intents():
            for order in ledger.orders_for_intent(intent["intent_id"]):
                if order["state"] != "FILLED":
                    continue
                fact = exchange.query_order(order["client_order_id"])
                self.assertAlmostEqual(
                    order["filled_qty"], fact.filled_qty, places=10,
                    msg=f"{order['client_order_id']} ledger≠exchange")
        # I4 持仓一致
        pos = exchange.position("BTCUSDT")
        fact_row = ledger.get_position_fact("BTCUSDT")
        if pos is None:
            self.assertEqual(fact_row["state"], PositionFactState.UNKNOWN.value)
        elif abs(pos.signed_qty) < 1e-12:
            self.assertEqual(fact_row["state"], PositionFactState.KNOWN_FLAT.value)
        else:
            self.assertEqual(fact_row["state"], PositionFactState.KNOWN_OPEN.value)
            self.assertAlmostEqual(fact_row["qty"], abs(pos.signed_qty), places=10)
        # I6 保护覆盖一致：独立 oracle（不复用生产覆盖计算）。
        # 仅对仍持仓且意图 PROTECTED 的场景断言；DEGRADED/恢复态由确定性套件覆盖。
        oracle = oracle_coverage(exchange, "BTCUSDT")
        if oracle["position"] > 1e-9:
            for intent in ledger.list_intents(
                    states=[IntentState.PROTECTED.value]):
                from aurora.kernel.coverage import compute_protection_status
                status = compute_protection_status(
                    ledger.orders_for_intent(intent["intent_id"]),
                    oracle["position"])
                self.assertAlmostEqual(
                    status.sl_coverage, oracle["sl"], places=9,
                    msg="ledger SL coverage diverges from independent oracle")
                self.assertAlmostEqual(
                    status.tp_coverage, oracle["tp"], places=9,
                    msg="ledger TP coverage diverges from independent oracle")
                self.assertTrue(
                    status.mandatory_ok,
                    msg="PROTECTED intent without mandatory SL coverage")
        return report

    @settings(
        max_examples=60, deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
    )
    @given(entry=BEHAVIORS, protection=BEHAVIORS, close_b=BEHAVIORS,
           ops=st.lists(OPS, max_size=8))
    def test_random_event_sequences_preserve_invariants(
        self, entry, protection, close_b, ops,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ledger.db")
            exchange = FakeExchange(
                entry_behavior=entry,
                protection_behavior=protection,
                close_behavior=close_b,
            )
            ledger = Ledger(path)
            orch = bind_explicit_protect_prices(
                Orchestrator(ledger, exchange, instance_id="prop"))
            orch.recover()
            seen_kill = False
            opened = False

            try:
                for op in ops:
                    if op == "open":
                        result = orch.open_position("LONG", 0.01, intent_id="P1")
                        if result.get("success"):
                            opened = True
                    elif op == "fire_sl":
                        order = exchange._orders.get("P1-SL")
                        if order and order["status"] == "NEW":
                            exchange.fire_protection("P1-SL", price=99.0)
                    elif op == "fire_tp":
                        order = exchange._orders.get("P1-TP")
                        if order and order["status"] == "NEW":
                            exchange.fire_protection("P1-TP", price=101.0)
                    elif op == "complete_entry":
                        order = exchange._orders.get("P1-ENTRY")
                        if order and order["status"] == "PARTIALLY_FILLED":
                            exchange.complete_fill("P1-ENTRY")
                    elif op == "close":
                        orch.close_position("property close")
                    elif op == "restart_recover":
                        ledger.close()
                        ledger = Ledger(path)
                        orch = bind_explicit_protect_prices(
                            Orchestrator(ledger, exchange, instance_id="prop2"))
                        self._assert_convergence(orch, exchange, ledger)
                    seen_kill = self._assert_invariants(
                        orch, exchange, ledger, seen_kill) or seen_kill

                # 终态恢复后必须收敛
                self._assert_convergence(orch, exchange, ledger)
                self._assert_invariants(orch, exchange, ledger, seen_kill)
            finally:
                ledger.close()


if __name__ == "__main__":
    unittest.main()
