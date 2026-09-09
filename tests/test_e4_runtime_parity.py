"""E4 — production overlay thesis matches E3 on the same closed daily bars."""
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.e3_walkforward import (  # noqa: E402
    DAY_MS,
    horizon_from_closed_slice,
    load_ohlc_csv,
)
from aurora.e4_runtime_parity import (  # noqa: E402
    append_forming_bar,
    compare_prefix,
    production_horizon,
    scan_closed_frame,
)
from aurora.feature_engine import FeatureEngine  # noqa: E402
from aurora.kernel.fake_exchange import FakeExchange  # noqa: E402
from aurora.kernel.ledger import Ledger  # noqa: E402
from aurora.kernel.orchestrator import Orchestrator  # noqa: E402
from aurora.p0_boundary import RunMode, SafetyViolation  # noqa: E402
from aurora.strategy_v2 import (  # noqa: E402
    DAILY_ADX_MIN,
    HORIZON_FETCH_LIMIT,
    MIN_HORIZON_BARS,
    OVERLAY_SIGNAL_SIZE_PCT,
    decide_overlay,
)
from aurora.trading_cycle import TradingCycle  # noqa: E402


T0 = 1609459200000


def _trend(n=120, start=20000.0, drift=80.0, t0=T0):
    rows = []
    px = start
    for i in range(n):
        o = px
        c = px + drift
        rows.append({
            "time": t0 + i * DAY_MS, "open": o,
            "high": max(o, c) + 40, "low": min(o, c) - 15,
            "close": c, "volume": 10.0,
        })
        px = c
    return pd.DataFrame(rows)


def _kline_rows(df: pd.DataFrame):
    rows = []
    for _, r in df.iterrows():
        t = int(r["time"])
        o, h, l, c = float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])
        v = float(r["volume"] if "volume" in df.columns else 1.0)
        rows.append([t, o, h, l, c, v, t + DAY_MS - 1, 0, 1, 0, 0, 0])
    return rows


def _minute_rows(n=80, close=100.0):
    rows = []
    for i in range(n):
        c = close + i * 0.1
        t = i * 60_000
        rows.append([t, c, c + 0.2, c - 0.2, c, 10.0, t + 59_999, 0, 1, 0, 0, 0])
    return rows


class FreezeTests(unittest.TestCase):
    def test_e2_overlay_constants_unchanged(self):
        self.assertEqual(OVERLAY_SIGNAL_SIZE_PCT, 0.10)
        self.assertEqual(DAILY_ADX_MIN, 20.0)
        self.assertEqual(HORIZON_FETCH_LIMIT, 1500)
        self.assertEqual(MIN_HORIZON_BARS, 60)


class HorizonParityTests(unittest.TestCase):
    def test_forming_bar_is_ignored_and_matches_e3(self):
        closed = _trend(90)
        cmp_ = compare_prefix(closed, overlay_open=False)
        self.assertTrue(cmp_["ok"], cmp_)
        live = production_horizon(
            append_forming_bar(closed), FeatureEngine(),
            now_ms=int(closed["time"].iloc[-1]) + DAY_MS,
        )
        self.assertNotAlmostEqual(live.close, float(closed["close"].iloc[-1]) * 2.0)
        self.assertAlmostEqual(live.close, float(closed["close"].iloc[-1]))

    def test_blind_last_row_drop_is_not_used_on_closed_frame(self):
        closed = _trend(90)
        e3 = horizon_from_closed_slice(closed, FeatureEngine())
        live = production_horizon(
            closed, FeatureEngine(),
            now_ms=int(closed["time"].iloc[-1]) + DAY_MS,
        )
        self.assertAlmostEqual(e3.close, live.close)
        self.assertEqual(e3.bar_open_time, live.bar_open_time)

    def test_synthetic_stream_matches(self):
        rows = scan_closed_frame(_trend(140), step=1)
        self.assertGreater(len(rows), 10)
        self.assertTrue(all(r["ok"] for r in rows), rows[-1])
        self.assertTrue(any(r["e3_action"] == "OPEN" for r in rows))


class CycleParityTests(unittest.TestCase):
    def test_paper_still_refuses_cycle(self):
        with self.assertRaises(SafetyViolation):
            TradingCycle(None, MagicMock(), mode=RunMode.PAPER)

    def test_cycle_directive_matches_e3_with_forming_bar(self):
        closed = _trend(90)
        live = append_forming_bar(closed)
        now_ms = int(closed["time"].iloc[-1]) + DAY_MS
        e3 = decide_overlay(
            horizon_from_closed_slice(closed, FeatureEngine()), False)

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

            client = MagicMock()
            client.futures_account.return_value = {
                "assets": [{"asset": "USDT", "availableBalance": "10000"}]}
            daily = _kline_rows(live)
            minute = _minute_rows()

            def klines(symbol, interval="1m", limit=120):
                return daily if interval == "1d" else minute

            client.futures_klines.side_effect = klines
            cycle = TradingCycle(RT(), client, mode=RunMode.TESTNET, capital=10000,
                                 evidence_path=os.path.join(tmp, "ev.json"))
            directive = cycle.overlay_directive(overlay_open=False, now_ms=now_ms)
            out = cycle.decide(pd.DataFrame(
                minute, columns=[
                    "time", "open", "high", "low", "close", "volume",
                    "close_time", "quote_volume", "trades",
                    "taker_buy_base", "taker_buy_quote", "ignore",
                ]
            ), now_ms=now_ms)
            self.assertEqual(directive.action, e3.action)
            self.assertEqual(out["strategy"]["action"], e3.action)
            self.assertEqual(len(exchange.submit_log), 0)
            ledger.close()


class OneMinuteNotAuthorityTests(unittest.TestCase):
    def test_one_minute_cannot_open_when_htf_says_hold(self):
        # Flat HTF: close sandwiched, ADX will be low-ish on tiny range.
        rows = []
        px = 30000.0
        for i in range(90):
            rows.append({
                "time": T0 + i * DAY_MS, "open": px, "high": px + 5,
                "low": px - 5, "close": px, "volume": 1.0,
            })
        closed = pd.DataFrame(rows)
        cmp_ = compare_prefix(closed, overlay_open=False)
        self.assertEqual(cmp_["e3_action"], "HOLD")
        self.assertEqual(cmp_["live_action"], "HOLD")


class EvidenceCsvTests(unittest.TestCase):
    def test_e3_csv_prefixes_match_when_present(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, "evidence", "e3", "btcusdt_1d.csv")
        df = load_ohlc_csv(path)
        if df is None or len(df) < MIN_HORIZON_BARS + 20:
            self.skipTest("E3 local CSV missing")
        rows = scan_closed_frame(df, step=40)
        self.assertGreater(len(rows), 5)
        bad = [r for r in rows if not r["ok"]]
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
