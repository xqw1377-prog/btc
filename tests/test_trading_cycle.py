"""闭环：收盘K、突破无未来函数、RiskGate 失败关闭、决策可下到内核。"""
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.feature_engine import FeatureEngine  # noqa: E402
from aurora.kernel.fake_exchange import FakeExchange  # noqa: E402
from aurora.kernel.ledger import Ledger  # noqa: E402
from aurora.kernel.orchestrator import Orchestrator  # noqa: E402
from aurora.kernel_types import Intent, RiskLevel, TradeIntent  # noqa: E402
from aurora.p0_boundary import RunMode, SafetyViolation  # noqa: E402
from aurora.risk_gate import RiskGate  # noqa: E402
from aurora.signal_providers import BreakoutSignalProvider  # noqa: E402
from aurora.trading_cycle import TradingCycle  # noqa: E402


def _ohlc(n=80, close=100.0, last_close=None):
    rows = []
    for i in range(n):
        c = close + i * 0.1
        rows.append({
            "time": i, "open": c, "high": c + 0.2, "low": c - 0.2,
            "close": c, "volume": 10.0, "close_time": i,
            "quote_volume": 0, "trades": 1, "taker_buy_base": 0,
            "taker_buy_quote": 0, "ignore": 0,
        })
    if last_close is not None:
        rows[-1]["close"] = last_close
        rows[-1]["high"] = max(rows[-1]["high"], last_close)
    return pd.DataFrame(rows)


class ClosedBarTests(unittest.TestCase):
    def test_features_ignore_forming_bar(self):
        df = _ohlc(40, last_close=999.0)
        feats = FeatureEngine().get_latest_features(df, exclude_forming=True)
        self.assertLess(feats["close"], 200.0)
        self.assertNotEqual(feats["close"], 999.0)

    def test_breakout_ignores_forming_spike(self):
        df = _ohlc(40, close=100.0)
        for i in df.index:
            df.loc[i, ["open", "high", "low", "close"]] = [100.0, 100.2, 99.8, 100.0]
        df.loc[df.index[-1], "high"] = 500.0
        df.loc[df.index[-1], "close"] = 500.0
        feats = FeatureEngine().get_latest_features(df, exclude_forming=True)
        sig = BreakoutSignalProvider().generate(feats, df)
        self.assertEqual(sig.direction, Intent.FLAT)


class RiskGateFailClosedTests(unittest.TestCase):
    def test_assess_exception_holds(self):
        gate = RiskGate(10000)
        gate.kernel.assess = MagicMock(side_effect=RuntimeError("boom"))
        intent = TradeIntent(
            action="OPEN", side=Intent.LONG, size_pct=0.2,
            stop_loss_pct=0.01, take_profit_pct=0.02, confidence=0.8,
            risk_level=RiskLevel.LOW, reason="test",
        )
        from aurora.kernel_types import PositionState
        out = gate.approve(intent, PositionState(), 0.01, "TREND", 0.8)
        self.assertEqual(out.action, "HOLD")
        self.assertEqual(out.risk_level, RiskLevel.BLOCKED)


class TradingCycleWireTests(unittest.TestCase):
    def test_paper_and_shadow_refuse_cycle(self):
        with self.assertRaises(SafetyViolation):
            TradingCycle(None, MagicMock(), mode=RunMode.PAPER)
        with self.assertRaises(SafetyViolation):
            TradingCycle(None, MagicMock(), mode=RunMode.SHADOW)

    def test_disabled_trading_does_not_submit(self):
        with tempfile.TemporaryDirectory() as tmp:
            exchange = FakeExchange()
            ledger = Ledger(os.path.join(tmp, "l.db"))
            orch = Orchestrator(ledger, exchange)
            orch.recover()

            class RT:
                def __init__(self):
                    self.orchestrator = orch
                    self.ledger = ledger
                    self.exchange = exchange

                def recover(self):
                    return orch.recover()

                def open_position(self, *a, **k):
                    raise AssertionError("must not submit when disabled")

                def close_position(self, *a, **k):
                    raise AssertionError("must not submit when disabled")

            client = MagicMock()
            client.futures_account.return_value = {"assets": [{"asset": "USDT", "availableBalance": "10000"}]}
            df = _ohlc(80)
            rows = [list(r) for r in df.itertuples(index=False, name=None)]
            client.futures_klines.return_value = rows
            cycle = TradingCycle(RT(), client, mode=RunMode.TESTNET, capital=10000)
            out = cycle.step(enable=False)
            self.assertFalse(out.get("submitted"))
            self.assertEqual(len(exchange.submit_log), 0)
            ledger.close()

    def test_enabled_open_uses_real_protect_prices(self):
        with tempfile.TemporaryDirectory() as tmp:
            exchange = FakeExchange()
            ledger = Ledger(os.path.join(tmp, "l.db"))
            orch = Orchestrator(ledger, exchange)
            orch.recover()
            from aurora.armed_runtime import ArmedRuntime
            rt = ArmedRuntime(RunMode.TESTNET, orch, ledger, exchange, {})
            client = MagicMock()
            client.futures_account.return_value = {"assets": [{"asset": "USDT", "availableBalance": "100000"}]}
            cycle = TradingCycle(rt, client, mode=RunMode.TESTNET, capital=100000)
            intent = TradeIntent(
                action="OPEN", side=Intent.LONG, size_pct=0.05,
                stop_loss_pct=0.01, take_profit_pct=0.02, confidence=0.9,
                risk_level=RiskLevel.LOW, reason="forced",
            )
            out = cycle.execute(
                {"intent": intent, "features": {"close": 100.0}, "reason": "forced"},
                enable=True,
            )
            self.assertTrue(out["submitted"])
            sl = [r for r in exchange.submit_log if r.order_kind.value == "STOP_LOSS"]
            self.assertEqual(len(sl), 1)
            self.assertAlmostEqual(sl[0].stop_price, 99.0)
            ledger.close()


class CustomProtectPriceTests(unittest.TestCase):
    def test_open_uses_passed_stop_and_tp(self):
        with tempfile.TemporaryDirectory() as tmp:
            exchange = FakeExchange()
            ledger = Ledger(os.path.join(tmp, "l.db"))
            orch = Orchestrator(ledger, exchange)
            orch.recover()
            result = orch.open_position(
                "LONG", 0.01, intent_id="PX1",
                stop_price=95.5, take_profit_price=110.25,
            )
            self.assertTrue(result["success"])
            sl = ledger.get_order("PX1-SL")
            tp = ledger.get_order("PX1-TP")
            self.assertAlmostEqual(sl["stop_price"], 95.5)
            self.assertAlmostEqual(tp["stop_price"], 110.25)
            ledger.close()


if __name__ == "__main__":
    unittest.main()
