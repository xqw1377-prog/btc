"""Observatory snapshot builders — capability honesty + fail-closed."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.observatory_snapshots import (  # noqa: E402
    CAP_D2_HOLD,
    CAP_PARTIAL,
    CAP_PROPOSED,
    CAP_STATIC,
    build_accounting_snapshot,
    build_decision_snapshot,
    build_eth_btc_snapshot,
    build_exchange_observation,
    build_governance_snapshot,
    build_observatory_bundle,
    build_trend_quant_snapshot,
    klines_records,
)
from aurora.strategy_v2 import HorizonSnapshot  # noqa: E402


def _bullish(**kwargs) -> HorizonSnapshot:
    base = dict(
        interval="1d",
        complete=True,
        close=120.0,
        ema20=110.0,
        ema60=100.0,
        ema_slope=1.0,
        adx=32.0,
        atr=2.0,
        vol_atr_pct=0.02,
        reason="fixture",
    )
    base.update(kwargs)
    return HorizonSnapshot(**base)


class TrendQuantTests(unittest.TestCase):
    def test_incomplete_htf_is_unknown_not_bull(self):
        snap = build_trend_quant_snapshot()
        self.assertEqual(snap["btc"]["trend_direction"], "UNKNOWN")
        self.assertEqual(snap["btc"]["trend_level"], "L0/5")
        self.assertEqual(snap["btc"]["action_eligibility"], "BLOCK_NEW_RISK")

    def test_3m_klines_populate_chart_slot(self):
        klines = [
            {"time": i * 180_000, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1.0}
            for i in range(80)
        ]
        snap = build_trend_quant_snapshot(btc_klines_3m=klines, market_meta={"status": "ok"})
        self.assertEqual(len(snap["charts"]["btc"]["klines"]), 80)
        self.assertIn("price", snap["charts"]["btc"]["metrics"])
        self.assertIn("timeframes", snap["btc"])


class DecisionAndExchangeTests(unittest.TestCase):
    def test_decision_never_live(self):
        trend = build_trend_quant_snapshot(market_meta={"status": "ok"})
        exchange = build_exchange_observation(
            {"positions": [], "positionsState": "FLAT", "equity": 1000},
            {"status": "NORMAL"},
            {"status": "ok", "updatedAt": "2026-01-01T00:00:00Z"},
        )
        dec = build_decision_snapshot(trend, exchange, eth_btc={"blockers": ["VALUE_TRUTH_UNKNOWN"]})
        self.assertFalse(dec["live"])
        self.assertEqual(dec["capability"], "READ-ONLY-DECISION")
        self.assertIn("candidate", dec)
        self.assertIn("left_card", dec)

    def test_exchange_unknown_never_flat(self):
        obs = build_exchange_observation(
            {"positions": [], "positionsState": "FLAT"},
            {"status": "UNKNOWN"},
            {"status": "unknown"},
        )
        self.assertEqual(obs["status"], "unknown")
        self.assertEqual(obs["positions"], "UNKNOWN")

    def test_eth_btc_unknown_without_klines(self):
        snap = build_eth_btc_snapshot()
        self.assertEqual(snap["capability"], CAP_PROPOSED)
        self.assertEqual(snap["status"], "unknown")
        self.assertIn("VALUE_TRUTH_UNKNOWN", snap["blockers"])


class AccountingAndGovernanceTests(unittest.TestCase):
    def test_accounting_missing_file_d2_hold(self):
        with tempfile.TemporaryDirectory() as tmp:
            snap = build_accounting_snapshot(ledger_search_root=tmp)
        self.assertEqual(snap["capability"], CAP_D2_HOLD)
        self.assertIsNone(snap["nav_btc"])

    def test_governance_execute_denied(self):
        gov = build_governance_snapshot(mode="TESTNET", execute_authorized=False)
        self.assertFalse(gov["execute_authorized"])
        self.assertEqual(gov["auto_testnet"], "DENIED")
        self.assertEqual(gov["live"], "NO_GO")


class EthBtcAllocationBundleTests(unittest.TestCase):
    def test_bundle_includes_allocation_fsm(self):
        from aurora.strategy_v2 import DAY_MS

        n = 120
        t0 = 1_700_000_000_000
        btc_k = [
            {"time": t0 + i * DAY_MS, "open": 100_000.0, "high": 100_100.0,
             "low": 99_900.0, "close": 100_000.0, "volume": 1.0}
            for i in range(n)
        ]
        eth_k = [
            {"time": t0 + i * DAY_MS, "open": 3500.0, "high": 3510.0,
             "low": 3490.0, "close": 3500.0, "volume": 1.0}
            for i in range(n)
        ]
        bundle = build_observatory_bundle(
            btc_klines_by_tf={"1d": btc_k, "3m": btc_k[-80:]},
            eth_klines_by_tf={"1d": eth_k, "3m": eth_k[-80:]},
            account_data={"positions": [], "positionsState": "FLAT", "assets": []},
            risk_data={"status": "NORMAL"},
            account_meta={"status": "ok", "updatedAt": "2026-01-01T00:00:00Z"},
            market_meta={"status": "ok"},
            mode="TESTNET",
        )
        eth_btc = bundle["eth_btc"]
        self.assertIn("allocation", eth_btc)
        self.assertIn(eth_btc["allocation"]["state"], (
            "BTC_DEFAULT", "ETH_CANDIDATE", "ETH_CONFIRMED",
            "ETH_HOLD", "ETH_WEAKENING", "BTC_RETURN",
        ))


class BundleTests(unittest.TestCase):
    def test_bundle_schema_and_honest_capabilities(self):
        bundle = build_observatory_bundle(
            btc_klines_by_tf={},
            eth_klines_by_tf={},
            account_data={"positions": [], "positionsState": "FLAT", "assets": []},
            risk_data={"status": "NORMAL"},
            account_meta={"status": "ok", "updatedAt": "2026-01-01T00:00:00Z"},
            market_meta={"status": "ok"},
            mode="TESTNET",
            execute_authorized=False,
        )
        self.assertEqual(bundle["schema"], "observatory-v1")
        self.assertEqual(bundle["trend_quant"]["capability"], CAP_PARTIAL)
        self.assertEqual(bundle["eth_btc"]["capability"], CAP_PROPOSED)
        self.assertEqual(bundle["event"]["capability"], "READ-ONLY-SEMANTICS")
        self.assertEqual(bundle["event"]["official_source_ingestion"], "NOT_CONNECTED")
        self.assertFalse(bundle["decision"]["live"])
        self.assertEqual(bundle["decision"]["capability"], "READ-ONLY-DECISION")
        self.assertIn("left_card", bundle["decision"])


class KlinesRecordsTests(unittest.TestCase):
    def test_klines_records_tail(self):
        import pandas as pd

        df = pd.DataFrame({
            "time": list(range(100)),
            "open": [1.0] * 100,
            "high": [2.0] * 100,
            "low": [0.5] * 100,
            "close": [1.5] * 100,
            "volume": [10.0] * 100,
        })
        rows = klines_records(df, tail=5)
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[-1]["time"], 99)


if __name__ == "__main__":
    unittest.main()
