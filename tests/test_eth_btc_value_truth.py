"""P2-B.1 ETH/BTC Value Truth — anti-lookahead + coordinate tests."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.eth_btc_value_truth import (  # noqa: E402
    FORBIDDEN_LIVE_FIELDS,
    LookaheadViolation,
    align_eth_btc_ratio_series,
    build_eth_btc_value_snapshot,
    classify_value_zone,
    compute_ex_post_cycle_progress,
)
from aurora.strategy_v2 import DAY_MS  # noqa: E402


def _daily_klines(base_ratio: float, n: int, *, start_time: int = 1_700_000_000_000) -> tuple:
    """Synthetic BTC flat @ 100k, ETH scaled for target ratio."""
    btc = []
    eth = []
    for i in range(n):
        t = start_time + i * DAY_MS
        btc.append({
            "time": t, "open": 100_000.0, "high": 100_100.0,
            "low": 99_900.0, "close": 100_000.0, "volume": 1.0,
        })
        eth_close = 100_000.0 * base_ratio * (1.0 + 0.001 * (i % 7 - 3))
        eth.append({
            "time": t, "open": eth_close, "high": eth_close * 1.001,
            "low": eth_close * 0.999, "close": eth_close, "volume": 1.0,
        })
    return btc, eth


class RatioSeriesTests(unittest.TestCase):
    def test_aligned_ratio_same_timestamp(self):
        btc, eth = _daily_klines(0.035, 80)
        now_ms = btc[-1]["time"] + DAY_MS + 1
        bars = align_eth_btc_ratio_series(btc, eth, now_ms=now_ms)
        self.assertEqual(len(bars), 80)
        self.assertAlmostEqual(bars[-1]["ratio"], eth[-1]["close"] / btc[-1]["close"], places=8)

    def test_forming_bar_excluded(self):
        btc, eth = _daily_klines(0.04, 10)
        # as_of before last bar closes
        now_ms = btc[-1]["time"] + DAY_MS - 1
        bars = align_eth_btc_ratio_series(btc, eth, now_ms=now_ms)
        self.assertEqual(len(bars), 9)


class ValueZoneTests(unittest.TestCase):
    def test_provisional_bands(self):
        self.assertEqual(classify_value_zone(0.10), "DEEP_CHEAP_ETH")
        self.assertEqual(classify_value_zone(0.20), "CHEAP_ETH")
        self.assertEqual(classify_value_zone(0.50), "FAIR")
        self.assertEqual(classify_value_zone(0.80), "EXPENSIVE_ETH")
        self.assertEqual(classify_value_zone(0.95), "EXTREME_EXPENSIVE_ETH")
        self.assertEqual(classify_value_zone(None), "UNKNOWN")


class SnapshotTests(unittest.TestCase):
    def test_insufficient_history_unknown(self):
        btc, eth = _daily_klines(0.035, 20)
        snap = build_eth_btc_value_snapshot(
            btc_klines_by_tf={"1d": btc},
            eth_klines_by_tf={"1d": eth},
            market_meta={"status": "ok"},
        )
        self.assertEqual(snap["value_zone"], "UNKNOWN")
        self.assertIn("INSUFFICIENT_HISTORY", snap["blockers"][1])

    def test_full_snapshot_fields(self):
        btc, eth = _daily_klines(0.035, 120)
        now_ms = btc[-1]["time"] + DAY_MS + 1
        snap = build_eth_btc_value_snapshot(
            btc_klines_by_tf={"1d": btc},
            eth_klines_by_tf={"1d": eth},
            market_meta={"status": "ok"},
            now_ms=now_ms,
        )
        self.assertEqual(snap["status"], "ok")
        self.assertIsNotNone(snap["ratio"])
        self.assertIsNotNone(snap["historical_percentile"])
        self.assertIsNotNone(snap["cycle_low_known"])
        self.assertIsNotNone(snap["cycle_high_known"])
        self.assertEqual(snap["signal"], "UNKNOWN")
        self.assertEqual(snap["source"], "SYNTHETIC_USDT_RATIO")
        for forbidden in FORBIDDEN_LIVE_FIELDS:
            self.assertNotIn(forbidden, snap)

    def test_ratio_unknown_blockers(self):
        snap = build_eth_btc_value_snapshot(market_meta={"status": "unknown"})
        self.assertIsNone(snap["ratio"])
        self.assertIn("VALUE_TRUTH_UNKNOWN", snap["blockers"])


class AntiLookaheadTests(unittest.TestCase):
    """B8 — future cycle high must not leak into live snapshot."""

    def test_cycle_high_known_ignores_future_bars(self):
        btc, eth = _daily_klines(0.03, 100)
        # First 60 bars cheap, then ramp — cut decision at bar 60
        for i in range(60, 100):
            eth[i]["close"] = 100_000.0 * 0.08  # much higher ratio later
            eth[i]["open"] = eth[i]["close"]
            eth[i]["high"] = eth[i]["close"] * 1.001
            eth[i]["low"] = eth[i]["close"] * 0.999

        cut_ms = btc[59]["time"] + DAY_MS + 1
        snap_at_60 = build_eth_btc_value_snapshot(
            btc_klines_by_tf={"1d": btc},
            eth_klines_by_tf={"1d": eth},
            market_meta={"status": "ok"},
            now_ms=cut_ms,
        )
        snap_full = build_eth_btc_value_snapshot(
            btc_klines_by_tf={"1d": btc},
            eth_klines_by_tf={"1d": eth},
            market_meta={"status": "ok"},
            now_ms=btc[-1]["time"] + DAY_MS + 1,
        )
        self.assertLess(
            snap_at_60["cycle_high_known"],
            snap_full["cycle_high_known"],
        )

    def test_forbidden_ex_post_fields_rejected(self):
        btc, eth = _daily_klines(0.035, 120)
        with self.assertRaises(LookaheadViolation):
            build_eth_btc_value_snapshot(
                btc_klines_by_tf={"1d": btc},
                eth_klines_by_tf={"1d": eth},
                market_meta={"status": "ok"},
                ex_post_cycle_progress=0.72,
            )

    def test_ex_post_helper_not_in_live_snapshot(self):
        btc, eth = _daily_klines(0.035, 120)
        ratios = [b["ratio"] for b in align_eth_btc_ratio_series(
            btc, eth, now_ms=btc[-1]["time"] + DAY_MS + 1,
        )]
        ex = compute_ex_post_cycle_progress(
            ratio_series=ratios,
            final_cycle_high=max(ratios) * 1.5,
        )
        self.assertIn("ex_post_cycle_progress", ex)
        self.assertIn("cycle_high_final", ex)
        snap = build_eth_btc_value_snapshot(
            btc_klines_by_tf={"1d": btc},
            eth_klines_by_tf={"1d": eth},
            market_meta={"status": "ok"},
        )
        self.assertNotIn("ex_post_cycle_progress", snap)
        self.assertNotIn("cycle_high_final", snap)


if __name__ == "__main__":
    unittest.main()
