"""P2-A.2 Funding Truth + OPEN eligibility tests."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.funding_truth import (  # noqa: E402
    apply_funding_open_eligibility,
    classify_funding_state,
    fetch_funding_snapshot,
)
from aurora.trend_truth import build_trend_snapshot  # noqa: E402


class FundingStateTests(unittest.TestCase):
    def test_unknown_rate_is_unknown_state(self):
        self.assertEqual(classify_funding_state(None), "UNKNOWN")

    def test_normal_rate(self):
        self.assertEqual(classify_funding_state(0.0001), "NORMAL")

    def test_fetch_never_uses_zero_for_missing(self):
        snap = fetch_funding_snapshot(None, "BTCUSDT")
        self.assertIsNone(snap["funding_rate"])
        self.assertEqual(snap["funding_state"], "UNKNOWN")

    def test_fetch_from_mark_price(self):
        class Client:
            def futures_mark_price(self, symbol=None):
                return {
                    "lastFundingRate": "0.00012",
                    "nextFundingTime": 1_700_000_000_000,
                    "time": 1_699_999_000_000,
                }

        snap = fetch_funding_snapshot(Client(), "BTCUSDT", market_freshness="ok")
        self.assertAlmostEqual(snap["funding_rate"], 0.00012)
        self.assertEqual(snap["funding_freshness"], "ok")
        self.assertIn(snap["funding_state"], ("NORMAL", "ELEVATED", "EXTREME"))

    def test_stale_market_freshness(self):
        snap = fetch_funding_snapshot(None, "BTCUSDT", market_freshness="stale")
        self.assertEqual(snap["funding_freshness"], "stale")
        self.assertIsNone(snap["funding_rate"])


class FundingEligibilityTests(unittest.TestCase):
    def test_unknown_funding_blocks_new_risk(self):
        action, blockers = apply_funding_open_eligibility(
            "LONG_ELIGIBLE",
            {"funding_freshness": "unknown", "funding_state": "UNKNOWN"},
        )
        self.assertEqual(action, "BLOCK_NEW_RISK")
        self.assertTrue(any("BLOCKED_BY_FUNDING" in b for b in blockers))

    def test_normal_funding_does_not_downgrade_level(self):
        klines = {
            "1d": [
                {"time": i * 86_400_000, "open": 100 + i, "high": 101 + i,
                 "low": 99 + i, "close": 100.5 + i, "volume": 1.0}
                for i in range(120)
            ],
        }
        snap = build_trend_snapshot(
            "BTC",
            klines,
            funding={
                "funding_rate": 0.0001,
                "funding_state": "NORMAL",
                "funding_freshness": "ok",
            },
        )
        self.assertIn(snap["trend_level"], ("L0/5", "L1/5", "L2/5", "L3/5", "L4/5", "L5/5"))
        self.assertEqual(snap["funding_rate"], 0.0001)
        snap_no_fund = build_trend_snapshot("BTC", klines, freshness="ok")
        self.assertEqual(snap["trend_level"], snap_no_fund["trend_level"])
        self.assertIn("trend_action", snap)

    def test_extreme_blocks_eligible_trend(self):
        action, _ = apply_funding_open_eligibility(
            "LONG_ELIGIBLE",
            {"funding_freshness": "ok", "funding_state": "EXTREME", "funding_rate": 0.002},
        )
        self.assertEqual(action, "BLOCK_NEW_RISK")

    def test_close_not_in_funding_gate(self):
        """Funding gate applies to OPEN/ADD only — CLOSE is out of scope here."""
        action, _ = apply_funding_open_eligibility(
            "HOLD",
            {"funding_freshness": "unknown", "funding_state": "UNKNOWN"},
        )
        self.assertEqual(action, "BLOCK_NEW_RISK")


if __name__ == "__main__":
    unittest.main()
