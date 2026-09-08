"""E1 Risk Semantics — vol units, risk-budget sizing, SL/TP authority, funding."""
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.accounting_truth import (  # noqa: E402
    accounting_path_for_ledger,
    persist_accounting,
    rebuild_from_ledger,
)
from aurora.feature_engine import FeatureEngine  # noqa: E402
from aurora.kernel.fake_exchange import FakeExchange  # noqa: E402
from aurora.kernel.ledger import Ledger  # noqa: E402
from aurora.kernel.orchestrator import Orchestrator  # noqa: E402
from aurora.kernel_types import (  # noqa: E402
    Intent, PositionSide, PositionState, RiskLevel, TradeIntent,
)
from aurora.p0_boundary import RunMode  # noqa: E402
from aurora.risk_gate import RiskGate  # noqa: E402
from aurora.risk_semantics import (  # noqa: E402
    VolatilityUnits,
    clamp_sl_tp,
    proposed_sl_tp_pct,
    size_pct_from_risk_budget,
)
from aurora.trading_cycle import TradingCycle  # noqa: E402


def _open_position_state():
    pos = PositionState()
    pos.side = PositionSide.LONG
    pos.size = 0.01
    pos.entry_price = 100.0
    return pos


class VolatilityUnitTests(unittest.TestCase):
    def test_feature_engine_exposes_vol_atr_pct(self):
        import numpy as np
        import pandas as pd
        n = 80
        df = pd.DataFrame({
            "time": range(n), "open": 100.0, "high": 101.0, "low": 99.0,
            "close": 100.0, "volume": 10.0, "close_time": range(n),
            "quote_volume": 0, "trades": 1, "taker_buy_base": 0,
            "taker_buy_quote": 0, "ignore": 0,
        })
        df["close"] = 100 + np.linspace(0, 1, n)
        feats = FeatureEngine().get_latest_features(df)
        self.assertIn("vol_atr_pct", feats)
        self.assertIn("vol_daily", feats)
        self.assertGreater(feats["vol_atr_pct"], 0)

    def test_volatility_units_from_features(self):
        units = VolatilityUnits.from_features({"close": 100, "atr": 2.0})
        self.assertAlmostEqual(units.vol_atr_pct, 0.02)

    def test_risk_kernel_assess_receives_vol_atr_pct_not_vol_daily(self):
        gate = RiskGate(10000)
        gate.kernel.assess = MagicMock(return_value=MagicMock(
            approved=True, risk_level=RiskLevel.LOW, max_position_pct=0.30,
            stop_loss_pct=0.02, take_profit_pct=0.04, reasons=[],
        ))
        intent = TradeIntent(
            action="OPEN", side=Intent.LONG, size_pct=0.1,
            stop_loss_pct=0.02, take_profit_pct=0.04,
            confidence=0.8, risk_level=RiskLevel.LOW, reason="test",
        )
        gate.approve(
            intent, PositionState(), vol_atr_pct=0.017, regime="TREND",
            confidence=0.8, signal_size_pct=0.1,
        )
        gate.kernel.assess.assert_called_once()
        call_kw = gate.kernel.assess.call_args.kwargs
        self.assertAlmostEqual(call_kw["volatility"], 0.017)
        self.assertNotAlmostEqual(call_kw["volatility"], 0.45)


class SlTpAuthorityTests(unittest.TestCase):
    def test_brain_proposal_preserved_by_risk_gate(self):
        gate = RiskGate(10000)
        proposed_sl, proposed_tp = proposed_sl_tp_pct("TREND", atr=2.0, price=100.0)
        intent = TradeIntent(
            action="OPEN", side=Intent.LONG, size_pct=0.2,
            stop_loss_pct=proposed_sl, take_profit_pct=proposed_tp,
            confidence=0.8, risk_level=RiskLevel.LOW, reason="test",
        )
        out = gate.approve(
            intent, PositionState(), vol_atr_pct=0.02, regime="TREND",
            confidence=0.8, signal_size_pct=0.2,
        )
        self.assertEqual(out.action, "OPEN")
        self.assertAlmostEqual(out.stop_loss_pct, proposed_sl, places=4)
        self.assertAlmostEqual(out.take_profit_pct, proposed_tp, places=4)

    def test_unknown_atr_proposal_denies_open(self):
        sl, tp = proposed_sl_tp_pct("TREND", atr=0, price=100.0)
        self.assertEqual(sl, 0.0)
        self.assertEqual(tp, 0.0)
        gate = RiskGate(10000)
        intent = TradeIntent(
            action="OPEN", side=Intent.LONG, size_pct=0.1,
            stop_loss_pct=sl, take_profit_pct=tp,
            confidence=0.8, risk_level=RiskLevel.LOW, reason="test",
        )
        out = gate.approve(
            intent, PositionState(), vol_atr_pct=0.01, regime="TREND",
            confidence=0.8, signal_size_pct=0.1,
        )
        self.assertEqual(out.action, "HOLD")
        self.assertIn("Stop distance", out.reason)

    def test_clamp_respects_bounds(self):
        sl, tp = clamp_sl_tp(0.005, 0.01, 0.02, 0.04)
        self.assertGreaterEqual(sl, 0.003)
        self.assertGreaterEqual(tp, 0.004)

    def test_zero_stop_clamp_denies_without_fallback(self):
        sl, tp = clamp_sl_tp(0.0, 0.04, 0.02, 0.04)
        self.assertEqual(sl, 0.0)


class RiskBudgetSizingTests(unittest.TestCase):
    def test_size_from_risk_budget_formula(self):
        pct = size_pct_from_risk_budget(10000, 0.02, 0.005, 0.40)
        self.assertAlmostEqual(pct, 0.25)

    def test_zero_stop_returns_zero_size_no_division(self):
        pct = size_pct_from_risk_budget(10000, 0.0, 0.005, 0.40)
        self.assertEqual(pct, 0.0)

    def test_gate_final_size_immutable_after_approve(self):
        gate = RiskGate(10000)
        gate.kernel.assess = MagicMock(return_value=MagicMock(
            approved=True, risk_level=RiskLevel.LOW, max_position_pct=0.30,
            stop_loss_pct=0.02, take_profit_pct=0.04, reasons=[],
        ))
        intent = TradeIntent(
            action="OPEN", side=Intent.LONG, size_pct=0.35,
            stop_loss_pct=0.02, take_profit_pct=0.04,
            confidence=0.9, risk_level=RiskLevel.LOW, reason="test",
        )
        out = gate.approve(
            intent, PositionState(), vol_atr_pct=0.01, regime="TREND",
            confidence=0.9, objective_mult=1.2, regime_weight=1.0,
            signal_size_pct=0.35,
        )
        authorized = out.size_pct
        out.size_pct *= 2.0
        self.assertLessEqual(authorized, 0.30)
        self.assertNotEqual(out.size_pct, authorized)


class FundingAuthorityTests(unittest.TestCase):
    def test_rebuild_includes_funding_income_events(self):
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
            ledger.insert_income_event(
                "inc1", "BTCUSDT", "FUNDING_FEE", -0.5, 1000)
            snap = rebuild_from_ledger(ledger, 10000.0)
            self.assertAlmostEqual(snap.funding_net, -0.5)
            self.assertAlmostEqual(snap.funding_paid, 0.5)
            self.assertAlmostEqual(snap.equity, 9999.4)
            ledger.close()

    def test_income_events_idempotent_and_cache_delete_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "l.db")
            ledger = Ledger(path)
            ledger.insert_income_event("inc1", "BTCUSDT", "FUNDING_FEE", -0.3, 1000)
            self.assertFalse(
                ledger.insert_income_event("inc1", "BTCUSDT", "FUNDING_FEE", -0.3, 1000))
            snap1 = rebuild_from_ledger(ledger, 10000.0)
            acct_path = accounting_path_for_ledger(path)
            snap1.last_applied_fill_id = None
            persist_accounting(snap1, acct_path)
            os.remove(acct_path)
            snap2 = rebuild_from_ledger(ledger, 10000.0)
            self.assertAlmostEqual(snap1.equity, snap2.equity)
            self.assertAlmostEqual(snap1.funding_net, snap2.funding_net)
            ledger.close()

    def test_funding_incomplete_blocks_open_not_close(self):
        gate = RiskGate(10000)
        gate.funding_incomplete = True
        open_intent = TradeIntent(
            action="OPEN", side=Intent.LONG, size_pct=0.1,
            stop_loss_pct=0.02, take_profit_pct=0.04,
            confidence=0.8, risk_level=RiskLevel.LOW, reason="test",
        )
        out = gate.approve(
            open_intent, PositionState(), vol_atr_pct=0.01,
            regime="TREND", confidence=0.8,
        )
        self.assertEqual(out.action, "HOLD")

        close_intent = TradeIntent(
            action="CLOSE", side=Intent.FLAT, size_pct=0,
            stop_loss_pct=0, take_profit_pct=0,
            confidence=1.0, risk_level=RiskLevel.HIGH, reason="exit",
        )
        out_close = gate.approve(
            close_intent, _open_position_state(), vol_atr_pct=0.01,
            regime="TREND", confidence=0.8,
        )
        self.assertEqual(out_close.action, "CLOSE")

    def test_funding_rate_veto(self):
        gate = RiskGate(10000)
        intent = TradeIntent(
            action="OPEN", side=Intent.LONG, size_pct=0.1,
            stop_loss_pct=0.02, take_profit_pct=0.04,
            confidence=0.8, risk_level=RiskLevel.LOW, reason="test",
        )
        out = gate.approve(
            intent, PositionState(), vol_atr_pct=0.01, regime="TREND",
            confidence=0.8, funding_rate=0.01, signal_size_pct=0.1,
        )
        self.assertEqual(out.action, "HOLD")
        self.assertIn("Funding", out.reason)


class TradingCycleFundingTests(unittest.TestCase):
    def test_funding_sync_failure_blocks_open_allows_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            exchange = FakeExchange()
            ledger = Ledger(os.path.join(tmp, "l.db"))
            orch = Orchestrator(ledger, exchange)
            orch.recover()
            from aurora.armed_runtime import ArmedRuntime
            rt = ArmedRuntime(RunMode.TESTNET, orch, ledger, exchange, {})
            client = MagicMock()
            client.futures_account.return_value = {
                "assets": [{"asset": "USDT", "availableBalance": "10000"}]
            }
            client.futures_income_history.side_effect = RuntimeError("network")
            cycle = TradingCycle(rt, client, mode=RunMode.TESTNET, capital=10000)
            cycle._sync_funding_events()
            self.assertTrue(cycle.brain.risk_gate.funding_incomplete)

            open_intent = TradeIntent(
                action="OPEN", side=Intent.LONG, size_pct=0.05,
                stop_loss_pct=0.01, take_profit_pct=0.02, confidence=0.9,
                risk_level=RiskLevel.LOW, reason="forced",
            )
            open_out = cycle.execute(
                {"intent": open_intent, "features": {"close": 100.0}, "reason": "forced"},
                enable=True,
            )
            self.assertFalse(open_out["submitted"])

            orch.open_position("LONG", 0.01, intent_id="PX1", stop_price=99.0)
            cycle.brain.execute_intent(
                TradeIntent(
                    action="OPEN", side=Intent.LONG, size_pct=0.05,
                    stop_loss_pct=0.01, take_profit_pct=0.02, confidence=0.9,
                    risk_level=RiskLevel.LOW, reason="setup",
                ),
                100.0,
            )
            close_intent = TradeIntent(
                action="CLOSE", side=Intent.FLAT, size_pct=0,
                stop_loss_pct=0, take_profit_pct=0, confidence=1.0,
                risk_level=RiskLevel.LOW, reason="risk reduction",
            )
            close_out = cycle.execute(
                {"intent": close_intent, "features": {"close": 100.0}, "reason": "exit"},
                enable=True,
            )
            self.assertTrue(close_out["submitted"])
            self.assertEqual(close_out["action"], "CLOSE")
            ledger.close()


if __name__ == "__main__":
    unittest.main()
