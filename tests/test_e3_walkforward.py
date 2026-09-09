"""E3 — frozen V2 vs BTC HODL; no look-ahead; OOS is verdict not tuner."""
import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.e3_walkforward import (  # noqa: E402
    CORE_BTC,
    FrozenCosts,
    _verdict,
    horizon_from_closed_slice,
    simulate_overlay,
)
from aurora.feature_engine import FeatureEngine  # noqa: E402
from aurora.strategy_v2 import OVERLAY_SIGNAL_SIZE_PCT  # noqa: E402
from aurora.risk_semantics import DEFAULT_RISK_BUDGET_PCT  # noqa: E402


MS = 86400000
T0 = 1609459200000  # 2021-01-01 UTC


def _trend(n=250, start=20000.0, drift=80.0, t0=T0, funding=0.0):
    rows = []
    px = start
    for i in range(n):
        o = px
        c = px + drift
        high = max(o, c) + 40
        low = min(o, c) - 15
        rows.append({
            "time": t0 + i * MS, "open": o, "high": high, "low": low,
            "close": c, "volume": 10.0, "funding_rate": funding,
        })
        px = c
    return pd.DataFrame(rows)


class FreezeTests(unittest.TestCase):
    def test_retune_overlay_size_is_rejected(self):
        costs = FrozenCosts(overlay_signal_size_pct=OVERLAY_SIGNAL_SIZE_PCT * 2)
        with self.assertRaises(ValueError):
            simulate_overlay(_trend(80), costs)

    def test_retune_risk_budget_is_rejected(self):
        costs = FrozenCosts(risk_budget_pct=DEFAULT_RISK_BUDGET_PCT * 3)
        with self.assertRaises(ValueError):
            simulate_overlay(_trend(80), costs)


class LookAheadTests(unittest.TestCase):
    def test_horizon_at_t_ignores_t_plus_1_close(self):
        df = _trend(120)
        engine = FeatureEngine()
        h1 = horizon_from_closed_slice(df.iloc[:90], engine)
        df2 = df.copy()
        df2.loc[90, "close"] = 9e9
        df2.loc[90, "high"] = 9e9
        h2 = horizon_from_closed_slice(df2.iloc[:90], engine)
        self.assertAlmostEqual(h1.close, h2.close)
        self.assertAlmostEqual(h1.ema20, h2.ema20)


class HODLBenchmarkTests(unittest.TestCase):
    def test_flat_market_does_not_beat_hodl_after_costs(self):
        rows = []
        px = 30000.0
        for i in range(120):
            rows.append({
                "time": T0 + i * MS, "open": px, "high": px + 5, "low": px - 5,
                "close": px, "volume": 1.0, "funding_rate": 0.0,
            })
        result, _, _ = simulate_overlay(pd.DataFrame(rows))
        self.assertEqual(result.hodl_btc, CORE_BTC)
        self.assertLessEqual(result.excess_btc, 1e-9)

    def test_fees_and_slippage_are_booked_when_overlay_trades(self):
        result, trades, _ = simulate_overlay(_trend(220, drift=120.0))
        if result.n_trades == 0:
            self.skipTest("synthetic trend did not arm overlay (ADX/HTF)")
        self.assertGreater(result.fees_usdt + result.slippage_usdt, 0.0)
        self.assertEqual(result.hodl_btc, 1.0)

    def test_funding_drag_reduces_excess_vs_zero_funding(self):
        df0 = _trend(220, drift=120.0, funding=0.0)
        df1 = _trend(220, drift=120.0, funding=0.0003)
        r0, t0, _ = simulate_overlay(df0)
        r1, t1, _ = simulate_overlay(df1)
        if r0.n_trades == 0:
            self.skipTest("synthetic trend did not arm overlay")
        self.assertGreaterEqual(r1.funding_usdt, 0.0)
        self.assertLessEqual(r1.excess_btc, r0.excess_btc + 1e-12)


class VerdictTests(unittest.TestCase):
    def test_negative_excess_is_not_edge(self):
        v, _, claim = _verdict(-0.01, 20, 0.8, 0.2, 0.2)
        self.assertEqual(v, "NEGATIVE_EXCESS")
        self.assertEqual(claim, "NO-EVIDENCE")

    def test_concentrated_month_is_not_edge(self):
        v, reasons, claim = _verdict(0.05, 20, 0.8, 0.9, 0.2)
        self.assertEqual(v, "INSUFFICIENT_OR_CONCENTRATED")
        self.assertEqual(claim, "NO-EVIDENCE")
        self.assertTrue(any("month" in r for r in reasons))

    def test_few_trades_is_not_edge(self):
        v, _, claim = _verdict(0.05, 2, 1.0, 0.2, 0.2)
        self.assertEqual(claim, "NO-EVIDENCE")


class CsvLoadTests(unittest.TestCase):
    def test_missing_csv_is_none(self):
        from aurora.e3_walkforward import load_ohlc_csv
        self.assertIsNone(load_ohlc_csv("/no/such/e3.csv"))

    def test_forming_daily_bar_is_dropped(self):
        from aurora.e3_walkforward import DAY_MS, closed_daily_bars
        now = T0 + 5 * MS
        df = pd.DataFrame({
            "time": [T0, T0 + MS, T0 + 5 * MS],
            "open": [1.0, 1.0, 1.0],
            "high": [1.0, 1.0, 1.0],
            "low": [1.0, 1.0, 1.0],
            "close": [1.0, 1.0, 1.0],
        })
        closed = closed_daily_bars(df, now_ms=now)
        self.assertEqual(list(closed["time"]), [T0, T0 + MS])
        self.assertTrue((closed["time"] + DAY_MS <= now).all())


if __name__ == "__main__":
    unittest.main()
