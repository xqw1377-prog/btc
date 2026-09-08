"""E0 Accounting Truth — fills 权威链、持久化与 TradingCycle 接线。"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.accounting_truth import (  # noqa: E402
    accounting_path_for_ledger,
    load_accounting,
    persist_accounting,
    rebuild_from_ledger,
    sync_brain_from_snapshot,
)
from aurora.kernel.fake_exchange import FakeExchange  # noqa: E402
from aurora.kernel.ledger import Ledger  # noqa: E402
from aurora.kernel.orchestrator import Orchestrator  # noqa: E402
from aurora.kernel_types import Intent, RiskLevel, TradeIntent  # noqa: E402
from aurora.p0_boundary import RunMode  # noqa: E402
from aurora.portfolio_brain_v2 import PortfolioBrainV2  # noqa: E402
from aurora.trading_cycle import TradingCycle  # noqa: E402


class LedgerAccountingTests(unittest.TestCase):
    def test_rebuild_net_pnl_includes_fees(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "l.db")
            ledger = Ledger(path)
            ledger.create_intent("T1", "BTCUSDT", "LONG", 0.01)
            ledger.record_order_submitting(
                client_order_id="T-ENTRY", intent_id="T1", order_kind="ENTRY",
                side="BUY", position_side="LONG", quantity=0.01)
            ledger.insert_fill(
                "f1", "T-ENTRY", 0.01, 100.0, fee=0.5, side="BUY",
                filled_at="2026-09-08T10:00:00+00:00", realized_pnl=0.0)
            ledger.record_order_submitting(
                client_order_id="T-CLOSE", intent_id="T1", order_kind="CLOSE",
                side="SELL", position_side="LONG", quantity=0.01, reduce_only=True)
            ledger.insert_fill(
                "f2", "T-CLOSE", 0.01, 101.0, fee=0.5, side="SELL",
                filled_at="2026-09-08T10:01:00+00:00", realized_pnl=0.01)
            snap = rebuild_from_ledger(ledger, 10000.0)
            self.assertAlmostEqual(snap.gross_realized_pnl, 0.01)
            self.assertAlmostEqual(snap.total_fees, 1.0)
            self.assertAlmostEqual(snap.net_pnl, -0.99)
            self.assertAlmostEqual(snap.equity, 9999.01)
            self.assertEqual(snap.closed_trade_count, 1)
            ledger.close()

    def test_persist_and_restart_rebuild_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "l.db")
            ledger = Ledger(path)
            ledger.create_intent("T1", "BTCUSDT", "LONG", 0.01)
            ledger.record_order_submitting(
                client_order_id="T-ENTRY", intent_id="T1", order_kind="ENTRY",
                side="BUY", position_side="LONG", quantity=0.01)
            ledger.insert_fill(
                "f1", "T-ENTRY", 0.01, 100.0, fee=0.1, side="BUY",
                filled_at="2026-09-08T10:00:00+00:00")
            acct_path = accounting_path_for_ledger(path)
            snap = rebuild_from_ledger(ledger, 5000.0)
            snap.last_applied_fill_id = "f1"
            persist_accounting(snap, acct_path)
            ledger.close()

            ledger2 = Ledger(path)
            snap2 = rebuild_from_ledger(ledger2, 5000.0)
            loaded = load_accounting(acct_path)
            self.assertAlmostEqual(loaded.equity, snap2.equity)
            self.assertAlmostEqual(loaded.net_pnl, snap2.net_pnl)
            os.remove(acct_path)
            snap3 = rebuild_from_ledger(ledger2, 5000.0)
            self.assertAlmostEqual(snap3.equity, snap2.equity)
            self.assertAlmostEqual(snap3.net_pnl, snap2.net_pnl)
            self.assertAlmostEqual(snap3.drawdown, snap2.drawdown)
            ledger2.close()

    def test_restart_brain_risk_objective_capital_agree(self):
        brain = PortfolioBrainV2(10000.0)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "l.db")
            ledger = Ledger(path)
            ledger.create_intent("T1", "BTCUSDT", "LONG", 0.01)
            ledger.record_order_submitting(
                client_order_id="T-ENTRY", intent_id="T1", order_kind="ENTRY",
                side="BUY", position_side="LONG", quantity=0.01)
            ledger.insert_fill(
                "f1", "T-ENTRY", 0.01, 100.0, fee=0.2, side="BUY",
                filled_at="2026-09-08T10:00:00+00:00")
            ledger.record_order_submitting(
                client_order_id="T-CLOSE", intent_id="T1", order_kind="CLOSE",
                side="SELL", position_side="LONG", quantity=0.01, reduce_only=True)
            ledger.insert_fill(
                "f2", "T-CLOSE", 0.01, 101.0, fee=0.2, side="SELL",
                filled_at="2026-09-08T10:01:00+00:00", realized_pnl=0.01)
            snap = rebuild_from_ledger(ledger, 10000.0)
            sync_brain_from_snapshot(brain, snap, ledger, last_applied_fill_id=None)
            self.assertAlmostEqual(brain.capital, snap.equity)
            self.assertAlmostEqual(brain.risk_gate.capital, snap.equity)
            self.assertAlmostEqual(brain.capital_objective.capital, snap.equity)
            ledger.close()


class BrainSyncTests(unittest.TestCase):
    def test_close_does_not_use_bar_price_pnl(self):
        brain = PortfolioBrainV2(10000.0)
        intent = TradeIntent(
            action="OPEN", side=Intent.LONG, size_pct=0.05,
            stop_loss_pct=0.01, take_profit_pct=0.02, confidence=0.9,
            risk_level=RiskLevel.LOW, reason="test",
        )
        brain.execute_intent(intent, 100.0)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "l.db")
            ledger = Ledger(path)
            ledger.create_intent("T1", "BTCUSDT", "LONG", 0.01)
            ledger.record_order_submitting(
                client_order_id="T-ENTRY", intent_id="T1", order_kind="ENTRY",
                side="BUY", position_side="LONG", quantity=0.05)
            ledger.insert_fill(
                "f1", "T-ENTRY", 0.05, 100.0, fee=0.2, side="BUY",
                filled_at="2026-09-08T10:00:00+00:00")
            ledger.record_order_submitting(
                client_order_id="T-CLOSE", intent_id="T1", order_kind="CLOSE",
                side="SELL", position_side="LONG", quantity=0.05, reduce_only=True)
            ledger.insert_fill(
                "f2", "T-CLOSE", 0.05, 102.0, fee=0.2, side="SELL",
                filled_at="2026-09-08T10:01:00+00:00", realized_pnl=0.10)
            snap = rebuild_from_ledger(ledger, 10000.0)
            sync_brain_from_snapshot(brain, snap, ledger, last_applied_fill_id=None)
            brain.execute_intent(
                TradeIntent(action="CLOSE", side=Intent.FLAT, size_pct=0,
                            stop_loss_pct=0, take_profit_pct=0, confidence=1.0,
                            risk_level=RiskLevel.LOW, reason="close"),
                price=999.0,
            )
            self.assertAlmostEqual(brain.capital, 9999.7)
            self.assertFalse(brain.position_mgr.position.is_open)
            ledger.close()


class TradingCycleAccountingTests(unittest.TestCase):
    def test_enabled_close_uses_ledger_not_kline(self):
        with tempfile.TemporaryDirectory() as tmp:
            exchange = FakeExchange(price=100.0)
            ledger_path = os.path.join(tmp, "l.db")
            ledger = Ledger(ledger_path)
            orch = Orchestrator(ledger, exchange)
            orch.recover()
            from aurora.armed_runtime import ArmedRuntime
            rt = ArmedRuntime(RunMode.TESTNET, orch, ledger, exchange, {})
            client = MagicMock()
            client.futures_account.return_value = {
                "assets": [{"asset": "USDT", "availableBalance": "10000"}]
            }
            cycle = TradingCycle(rt, client, mode=RunMode.TESTNET, capital=10000)
            orch.open_position(
                "LONG", 0.01, intent_id="PX1",
                stop_price=99.0, take_profit_price=101.0)
            exchange.price = 102.0
            orch.close_position("test close")
            before = cycle.brain.capital
            intent = TradeIntent(
                action="CLOSE", side=Intent.FLAT, size_pct=0,
                stop_loss_pct=0, take_profit_pct=0, confidence=1.0,
                risk_level=RiskLevel.LOW, reason="forced",
            )
            out = cycle.execute(
                {"intent": intent, "features": {"close": 50.0}, "reason": "forced"},
                enable=True,
            )
            self.assertTrue(out["submitted"])
            self.assertAlmostEqual(cycle.brain.capital, before)
            acct_path = accounting_path_for_ledger(ledger_path)
            self.assertTrue(os.path.exists(acct_path))
            with open(acct_path) as fh:
                data = json.load(fh)
            self.assertIn("equity", data)
            ledger.close()


if __name__ == "__main__":
    unittest.main()
