"""P2-A Dual-Asset HTF Trend Truth tests."""
import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.trend_truth import (  # noqa: E402
    build_dual_asset_trend_truth,
    build_trend_snapshot,
    relative_strength,
)


def _uptrend_klines(n: int, base: float = 100.0, step: float = 0.5, interval_ms: int = 86_400_000):
    rows = []
    price = base
    for i in range(n):
        o = price
        c = price + step
        rows.append({
            "time": i * interval_ms,
            "open": o,
            "high": c + 0.2,
            "low": o - 0.1,
            "close": c,
            "volume": 1000.0,
        })
        price = c
    return rows


class TrendSnapshotTests(unittest.TestCase):
    def test_missing_1d_is_l0_unknown(self):
        snap = build_trend_snapshot("BTC", {})
        self.assertEqual(snap["trend_level"], "L0/5")
        self.assertEqual(snap["trend_direction"], "UNKNOWN")
        self.assertEqual(snap["action_eligibility"], "BLOCK_NEW_RISK")

    def test_dual_asset_includes_relative_strength(self):
        klines = {"1d": _uptrend_klines(120), "4h": _uptrend_klines(120, interval_ms=14_400_000),
                  "1h": _uptrend_klines(120, interval_ms=3_600_000), "3m": _uptrend_klines(80, interval_ms=180_000)}
        truth = build_dual_asset_trend_truth(
            btc_klines_by_tf=klines,
            eth_klines_by_tf=klines,
            market_meta={"status": "ok"},
        )
        self.assertIn("relative_strength", truth)
        self.assertIn("btc", truth)
        self.assertIn("eth", truth)
        self.assertIn("timeframes", truth["btc"])

    def test_4h_bear_blocks_long_eligible(self):
        bull = _uptrend_klines(120)
        bear = []
        p = 100.0
        for i in range(120):
            o = p
            c = p - 0.5
            bear.append({"time": i * 14_400_000, "open": o, "high": o, "low": c - 0.2, "close": c, "volume": 1.0})
            p = c
        snap = build_trend_snapshot(
            "BTC",
            {"1d": bull, "4h": bear, "1h": bull, "3m": bull[:80]},
            freshness="ok",
        )
        if snap["trend_level_num"] >= 3:
            self.assertNotEqual(snap["action_eligibility"], "LONG_ELIGIBLE")

    def test_relative_strength_btc_preferred(self):
        btc = {"trend_level_num": 4, "trend_level": "L4/5", "adx": 30}
        eth = {"trend_level_num": 2, "trend_level": "L2/5", "adx": 22}
        rs = relative_strength(btc, eth)
        self.assertEqual(rs["label"], "BTC > ETH")


if __name__ == "__main__":
    unittest.main()
