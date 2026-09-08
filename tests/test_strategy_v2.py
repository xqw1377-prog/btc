"""E2 Strategy V2 — BTC HODL identity, HTF overlay, no 1m authority."""
import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.kernel_types import Intent, RiskLevel, Signal  # noqa: E402
from aurora.portfolio_brain_v2 import PortfolioBrainV2  # noqa: E402
from aurora.strategy_v2 import (  # noqa: E402
    FORBIDDEN,
    NUMERAIRE,
    HorizonSnapshot,
    decide_overlay,
    horizon_from_frame,
    reject_short,
)


def _bullish(**kwargs) -> HorizonSnapshot:
    base = dict(
        interval="1d", complete=True, close=120.0, ema20=110.0, ema60=100.0,
        ema_slope=1.0, adx=30.0, atr=2.0, vol_atr_pct=0.02, reason="fixture",
    )
    base.update(kwargs)
    return HorizonSnapshot(**base)


def _signals_1m_long():
    return [
        Signal(source="trend", direction=Intent.LONG, confidence=0.9,
               timeframe="1m", reason="fake"),
        Signal(source="mr", direction=Intent.LONG, confidence=0.9,
               timeframe="1m", reason="fake"),
    ]


class ThesisContractTests(unittest.TestCase):
    def test_numeraire_is_btc_not_usdt(self):
        self.assertEqual(NUMERAIRE, "BTC")
        self.assertIn("USDT_PNL_OBJECTIVE", FORBIDDEN)
        self.assertIn("NET_SHORT", FORBIDDEN)
        self.assertIn("1M_SIGNAL_AUTHORITY", FORBIDDEN)

    def test_default_is_core_hodl(self):
        d = decide_overlay(HorizonSnapshot("1d", False, reason="missing"), False)
        self.assertEqual(d.sleeve, "CORE")
        self.assertEqual(d.action, "HOLD")
        self.assertEqual(d.thesis, "HOLD_BTC")

    def test_htf_incomplete_denies_overlay_open(self):
        d = decide_overlay(HorizonSnapshot("1d", False, reason="HTF bars 3 < 60"), False)
        self.assertEqual(d.action, "HOLD")
        self.assertIn("OPEN denied", d.reason)

    def test_htf_incomplete_does_not_force_overlay_close(self):
        d = decide_overlay(HorizonSnapshot("1d", False, reason="missing"), True)
        self.assertEqual(d.action, "HOLD")
        self.assertEqual(d.sleeve, "OVERLAY")

    def test_bullish_htf_opens_long_only(self):
        d = decide_overlay(_bullish(), False)
        self.assertEqual(d.action, "OPEN")
        self.assertEqual(d.side, Intent.LONG)
        self.assertEqual(d.thesis, "OVERLAY_LONG")

    def test_close_at_or_below_ema20_denies_overlay_open(self):
        self.assertNotEqual(
            decide_overlay(_bullish(close=110.0, ema20=110.0), False).action, "OPEN")
        self.assertNotEqual(
            decide_overlay(_bullish(close=109.0, ema20=110.0), False).action, "OPEN")

    def test_ema20_at_or_below_ema60_denies_overlay_open(self):
        self.assertNotEqual(
            decide_overlay(_bullish(ema20=100.0, ema60=100.0), False).action, "OPEN")
        self.assertNotEqual(
            decide_overlay(_bullish(ema20=99.0, ema60=100.0), False).action, "OPEN")

    def test_adx_below_20_denies_overlay_open(self):
        self.assertNotEqual(
            decide_overlay(_bullish(adx=19.9), False).action, "OPEN")

    def test_broken_htf_closes_overlay(self):
        d = decide_overlay(_bullish(close=90.0, ema20=110.0, ema60=100.0), True)
        self.assertEqual(d.action, "CLOSE")
        self.assertEqual(d.thesis, "EXIT_OVERLAY")

    def test_never_proposes_short(self):
        for open_ in (False, True):
            d = decide_overlay(_bullish(close=90.0, ema20=110.0, ema60=120.0), open_)
            self.assertNotEqual(d.side, Intent.SHORT)
            self.assertFalse(reject_short(d.side, d.action) and d.action == "OPEN")
        self.assertTrue(reject_short(Intent.SHORT, "OPEN"))


class HorizonFrameTests(unittest.TestCase):
    def test_short_frame_is_incomplete(self):
        df = pd.DataFrame({
            "time": range(10), "open": 100.0, "high": 101.0, "low": 99.0,
            "close": 100.0, "volume": 1.0,
        })
        snap = horizon_from_frame(df)
        self.assertFalse(snap.complete)

    def test_none_frame_is_incomplete(self):
        self.assertFalse(horizon_from_frame(None).complete)


class BrainAuthorityTests(unittest.TestCase):
    def test_one_minute_signals_cannot_open_without_htf(self):
        brain = PortfolioBrainV2(10000)
        intent = brain.process(
            signals=_signals_1m_long(),
            regime="TREND", confidence=0.9, volatility=0.02,
            price=100.0, atr=2.0, current_ts=1.0,
            features={"close": 100.0, "atr": 2.0, "vol_atr_pct": 0.02},
            strategy_directive=decide_overlay(
                HorizonSnapshot("1d", False, reason="missing"), False),
        )
        self.assertEqual(intent.action, "HOLD")
        self.assertNotEqual(intent.side, Intent.SHORT)

    def test_htf_bullish_proposes_long_not_short(self):
        brain = PortfolioBrainV2(10000)
        d = decide_overlay(_bullish(), False)
        intent = brain.process(
            signals=[
                Signal(source="trend", direction=Intent.SHORT, confidence=0.99,
                       timeframe="1m", reason="should be ignored"),
            ],
            regime="RANGE", confidence=0.2, volatility=0.4,
            price=100.0, atr=0.1, current_ts=1.0,
            features={"close": 100.0, "atr": 0.1, "vol_atr_pct": 0.001},
            strategy_directive=d,
        )
        if intent.action == "OPEN":
            self.assertEqual(intent.side, Intent.LONG)
        else:
            self.assertEqual(intent.action, "HOLD")

    def test_htf_exit_closes_overlay_not_blocked_by_1m_long(self):
        brain = PortfolioBrainV2(10000)
        brain.position_mgr.open(
            Intent.LONG, 0.01, 100.0, 90.0, 130.0, "overlay")
        intent = brain.process(
            signals=_signals_1m_long(),
            regime="TREND", confidence=0.9, volatility=0.02,
            price=100.0, atr=2.0, current_ts=1.0,
            features={"close": 100.0, "atr": 2.0, "vol_atr_pct": 0.02},
            strategy_directive=decide_overlay(
                _bullish(close=90.0), True),
        )
        self.assertEqual(intent.action, "CLOSE")
        self.assertIn("thesis broken", intent.reason)

    def test_htf_unknown_denies_open_allows_stop_close(self):
        unknown = HorizonSnapshot("1d", False, reason="stale")
        self.assertEqual(decide_overlay(unknown, False).action, "HOLD")
        self.assertEqual(decide_overlay(unknown, True).action, "HOLD")
        brain = PortfolioBrainV2(10000)
        brain.position_mgr.open(
            Intent.LONG, 0.01, 100.0, 99.0, 130.0, "overlay")
        intent = brain.process(
            signals=_signals_1m_long(),
            regime="TREND", confidence=0.9, volatility=0.02,
            price=98.0, atr=2.0, current_ts=1.0,
            features={"close": 98.0, "atr": 2.0, "vol_atr_pct": 0.02},
            strategy_directive=decide_overlay(unknown, True),
        )
        self.assertEqual(intent.action, "CLOSE")
        self.assertIn("Stop loss", intent.reason)

    def test_stop_hit_still_closes_when_htf_intact(self):
        brain = PortfolioBrainV2(10000)
        brain.position_mgr.open(
            Intent.LONG, 0.01, 100.0, 99.0, 130.0, "overlay")
        intent = brain.process(
            signals=_signals_1m_long(),
            regime="TREND", confidence=0.9, volatility=0.02,
            price=98.0, atr=2.0, current_ts=1.0,
            features={"close": 98.0, "atr": 2.0, "vol_atr_pct": 0.02},
            strategy_directive=decide_overlay(_bullish(), True),
        )
        self.assertEqual(intent.action, "CLOSE")
        self.assertIn("Stop loss", intent.reason)


if __name__ == "__main__":
    unittest.main()
