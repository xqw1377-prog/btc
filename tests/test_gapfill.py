"""GAPFILL 三模块离线测试：E5 前瞻账 / LIVE endpoint 合同 / 密钥轮换检查。"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from aurora.e5_forward import (
    forward_csv_path,
    forward_ledger_path,
    frozen_params_fingerprint,
    last_recorded_bar,
    overlay_open_state,
    record_forward_entry,
)
from aurora.live_endpoint_contract import (
    LIVE_CONSTRUCTION_HOSTS,
    LIVE_ENDPOINT_CONTRACT_VERSION,
    LIVE_TRADING_HOSTS,
    assert_live_endpoint_policy,
    effective_live_hosts,
    live_authorization_facts,
)
from aurora.p0_boundary import SafetyViolation, ALLOWED_LIVE_HOSTS

DAY = 86_400_000


def _csv(tmp, n=80, start=1_700_000_000_000):
    rows = []
    price = 50_000.0
    for i in range(n):
        t = start + i * DAY
        price *= 1.001
        rows.append({"time": t, "open": price, "high": price * 1.01,
                     "low": price * 0.99, "close": price,
                     "volume": 100.0, "funding_rate": 0.0001})
    path = os.path.join(tmp, "btcusdt_1d.csv")
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


class ForwardLedgerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.csv = _csv(self._tmp.name)
        self.ledger = os.path.join(self._tmp.name, "forward_ledger.jsonl")
        self.now = 1_700_000_000_000 + 81 * DAY  # 所有 bar 已收盘

    def test_first_entry_appends_and_is_point_in_time(self):
        out = record_forward_entry(csv_path=self.csv, ledger_path=self.ledger,
                                   now_ms=self.now)
        self.assertTrue(out["appended"])
        entry = out["entry"]
        self.assertGreaterEqual(entry["recorded_at_ms"], entry["bar_close_ms"])
        self.assertTrue(entry["frozen_params_fingerprint"])
        self.assertEqual(entry["edge_claim"], "FORWARD-RECORD-ONLY")
        self.assertEqual(entry["skipped_bars"], None)
        self.assertTrue(os.path.exists(self.ledger))

    def test_same_bar_idempotent_refusal(self):
        record_forward_entry(csv_path=self.csv, ledger_path=self.ledger,
                             now_ms=self.now)
        again = record_forward_entry(csv_path=self.csv,
                                     ledger_path=self.ledger, now_ms=self.now)
        self.assertFalse(again["appended"])
        with open(self.ledger) as fh:
            self.assertEqual(sum(1 for _ in fh), 1)

    def test_gap_is_registered_not_silently_backfilled(self):
        record_forward_entry(csv_path=self.csv, ledger_path=self.ledger,
                             now_ms=self.now)
        # 追加两根新 bar 后再记录：只记最新，缺口如实登记
        rows = pd.read_csv(self.csv).to_dict("records")
        base = rows[-1]
        for k in range(1, 3):
            r = dict(base)
            r["time"] = int(base["time"]) + k * DAY
            rows.append(r)
        grown = os.path.join(self._tmp.name, "grown.csv")
        pd.DataFrame(rows).to_csv(grown, index=False)
        later = self.now + 3 * DAY
        out = record_forward_entry(csv_path=grown, ledger_path=self.ledger,
                                   now_ms=later)
        self.assertTrue(out["appended"])
        self.assertEqual(out["entry"]["skipped_bars"], 1)
        self.assertTrue(out["entry"]["catchup"])

    def test_future_bar_refused(self):
        with self.assertRaises(ValueError):
            record_forward_entry(csv_path=self.csv, ledger_path=self.ledger,
                                 now_ms=1_700_000_000_000)  # 早于所有收盘

    def test_overlay_state_derived_from_ledger(self):
        record_forward_entry(csv_path=self.csv, ledger_path=self.ledger,
                             now_ms=self.now)
        # 状态可推导（具体布尔取决于冻结规则；断言可推导不崩即可）
        self.assertIsInstance(overlay_open_state(self.ledger), bool)
        self.assertIsInstance(last_recorded_bar(self.ledger), int)

    def test_params_fingerprint_stable(self):
        self.assertEqual(frozen_params_fingerprint(),
                         frozen_params_fingerprint())


class LiveEndpointContractTests(unittest.TestCase):
    UNARMED = {"ALLOW_LIVE_TRADING": "true",
               "AURORA_LIVE_CONFIRM": "I_UNDERSTAND_LIVE_RISK"}
    ARMED = {**UNARMED, "AURORA_ARM_LIVE": "I_ARM_LIVE_EXECUTION",
             "AURORA_LIVE_ENDPOINT_CONTRACT": LIVE_ENDPOINT_CONTRACT_VERSION}

    def test_unarmed_blocks_construction_spot_host(self):
        with self.assertRaises(SafetyViolation) as hc:
            assert_live_endpoint_policy("api.binance.com", "construction",
                                        environ=self.UNARMED)
        self.assertIn("full LIVE authorization", str(hc.exception))

    def test_unarmed_effective_hosts_stay_default(self):
        self.assertEqual(effective_live_hosts(self.UNARMED), ALLOWED_LIVE_HOSTS)

    def test_fully_authorized_construction_allows_spot_ping(self):
        assert_live_endpoint_policy("api.binance.com", "construction",
                                    environ=self.ARMED)
        assert_live_endpoint_policy("fapi.binance.com", "construction",
                                    environ=self.ARMED)

    def test_trading_phase_never_allows_spot_even_authorized(self):
        with self.assertRaises(SafetyViolation):
            assert_live_endpoint_policy("api.binance.com", "trading",
                                        environ=self.ARMED)

    def test_unknown_host_always_refused(self):
        for env in (self.UNARMED, self.ARMED):
            with self.assertRaises(SafetyViolation):
                assert_live_endpoint_policy("evil.example.com",
                                            "construction", environ=env)

    def test_facts_observed_not_mutated(self):
        facts = live_authorization_facts(self.UNARMED)
        self.assertFalse(facts["arm_token"])
        self.assertFalse(facts["endpoint_contract"])


if __name__ == "__main__":
    unittest.main()
