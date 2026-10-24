"""P3-R2 Observatory Final Decision Mirror — R2-1~R2-12 acceptance."""
from __future__ import annotations

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from aurora.decision_observatory import (  # noqa: E402
    CAP_DECISION,
    build_decision_observatory_snapshot,
)
from aurora.observatory_snapshots import (  # noqa: E402
    CAP_PROPOSED,
    build_decision_snapshot,
    build_exchange_observation,
    build_observatory_bundle,
    build_trend_quant_snapshot,
)
from tests.fixtures.decision_observatory_r2_cases import (  # noqa: E402
    AUTHORITATIVE_CURRENT,
    ETH_BTC_CONFIRMED,
    ETH_BTC_FAIR,
    EVENT_NOT_CONNECTED,
    EXCHANGE_OK_NO_MIX,
    EXCHANGE_UNKNOWN,
    RISK_OFF_SCENARIO,
    TREND_L5_L3,
)


def _snap(**kw):
    base = {
        "trend_quant": TREND_L5_L3,
        "eth_btc": ETH_BTC_CONFIRMED,
        "event_bundle": EVENT_NOT_CONNECTED,
        "exchange": EXCHANGE_UNKNOWN,
        "account_meta": {"status": "unknown"},
    }
    base.update(kw)
    return build_decision_observatory_snapshot(**base)


class R2AcceptanceTests(unittest.TestCase):
    def test_r2_1_real_brain_not_proposed_fixture(self):
        snap = _snap()
        self.assertEqual(snap["capability"], CAP_DECISION)
        self.assertIn("candidate", snap)
        self.assertEqual(snap["candidate"]["runtime_kind"], "P3_DECISION_BRAIN_READ_ONLY")
        self.assertIn("left_card", snap)
        self.assertIn("right_evidence", snap)
        self.assertNotEqual(snap.get("headline"), "NOT LIVE DECISION")

    def test_r2_2_projection_only_no_second_brain_in_observatory(self):
        path = os.path.join(ROOT, "aurora-dashboard", "src", "cockpit", "decisionMirror.js")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        for banned in ("evaluate_decision", "P0 TRUTH", "CRYPTO_BETA_CLUSTER", "normalize_trend"):
            self.assertNotIn(banned, src)

    def test_r2_3_account_unknown_current_not_fabricated(self):
        snap = _snap()
        cur = snap["candidate"]["current_state"]
        self.assertEqual(cur["status"], "UNKNOWN")
        self.assertIsNone(cur["btc"])
        self.assertIsNone(cur["eth"])

    def test_r2_4_target_candidate_with_delta_unavailable(self):
        snap = _snap()
        self.assertEqual(snap["target_status"], "CANDIDATE")
        self.assertEqual(snap["delta_status"], "UNAVAILABLE")
        lc = snap["left_card"]
        self.assertIn("TARGET CANDIDATE", lc["headlines"][0])
        self.assertEqual(lc["delta_status"], "UNAVAILABLE")
        self.assertNotIn("UNKNOWN", lc["headlines"][0])

    def test_r2_5_authoritative_current_layers_consistent(self):
        snap = build_decision_observatory_snapshot(
            trend_quant=TREND_L5_L3,
            eth_btc=ETH_BTC_CONFIRMED,
            event_bundle=EVENT_NOT_CONNECTED,
            exchange=EXCHANGE_OK_NO_MIX,
            account_meta={"status": "ok", "version": "a-v1"},
            authoritative_current=AUTHORITATIVE_CURRENT,
        )
        cand = snap["candidate"]
        self.assertEqual(cand["current_state"]["status"], "KNOWN")
        self.assertEqual(cand["delta_proposal"]["status"], "AVAILABLE")
        self.assertAlmostEqual(cand["delta_proposal"]["eth"], 10.0)
        right = snap["right_evidence"]
        self.assertEqual(right["current"]["btc"], 80.0)
        self.assertEqual(right["target_candidate"]["eth"], 20.0)

    def test_r2_6_risk_off_precedence_in_trace(self):
        snap = build_decision_observatory_snapshot(
            trend_quant=TREND_L5_L3,
            eth_btc=ETH_BTC_FAIR,
            event_bundle=EVENT_NOT_CONNECTED,
            exchange=EXCHANGE_OK_NO_MIX,
            account_meta={"status": "ok"},
            authoritative_current=AUTHORITATIVE_CURRENT,
            fixture_event_pipeline=RISK_OFF_SCENARIO["fixture_pipeline"],
        )
        trace = snap["decision_trace"]
        self.assertEqual(trace["winner"], "P2")
        stages = {s["stage"]: s["status"] for s in trace["stages"]}
        self.assertEqual(stages["P2 DEFENSIVE"], "RISK_OFF ELIGIBLE")
        self.assertEqual(stages["P3 SPOT"], "SUPPRESSED BY P2")
        self.assertEqual(snap["candidate"]["event_action"], "RISK_OFF")

    def test_r2_7_crypto_beta_cluster_visualized(self):
        snap = _snap(
            exchange=EXCHANGE_OK_NO_MIX,
            account_meta={"status": "ok"},
            authoritative_current=AUTHORITATIVE_CURRENT,
            eth_btc=ETH_BTC_FAIR,
        )
        cluster = snap["right_evidence"]["why"]["crypto_beta_cluster"]
        self.assertEqual(cluster["combined_state"], "CLUSTERED")
        self.assertEqual(cluster["independent_full_budgets"], "NOT ALLOWED")
        self.assertGreater(cluster["btc_overlay_request"], 0)
        self.assertGreater(cluster["eth_overlay_request"], 0)

    def test_r2_8_event_increment_request_not_final_amount(self):
        snap = build_decision_observatory_snapshot(
            trend_quant=TREND_L5_L3,
            eth_btc=ETH_BTC_FAIR,
            event_bundle=EVENT_NOT_CONNECTED,
            exchange=EXCHANGE_OK_NO_MIX,
            account_meta={"status": "ok"},
            authoritative_current=AUTHORITATIVE_CURRENT,
            fixture_event_pipeline=RISK_OFF_SCENARIO["fixture_pipeline"],
        )
        ev = snap["right_evidence"]["why"]["event_increment"]
        self.assertEqual(ev["final_risk_amount"], "NOT DECIDED")
        self.assertNotIn("BOOST +", json.dumps(snap["left_card"]))

    def test_r2_9_authority_disclaimers_present(self):
        snap = _snap()
        auth = snap["right_evidence"]["authority"]
        self.assertEqual(auth["riskgate"], "NOT APPLIED")
        self.assertFalse(auth["submit_allowed"])
        self.assertTrue(auth["target_not_order"])
        self.assertTrue(auth["delta_not_execution"])
        self.assertIn("TARGET ≠ ORDER", snap["left_card"]["meta"])

    def test_r2_10_riskgate_not_applied_submit_denied(self):
        snap = _snap()
        self.assertFalse(snap["submit_allowed"])
        self.assertFalse(snap["candidate"]["submit_allowed"])

    def test_r2_11_idempotent_decision_key(self):
        first = build_decision_observatory_snapshot(
            trend_quant=TREND_L5_L3,
            eth_btc=ETH_BTC_CONFIRMED,
            event_bundle=EVENT_NOT_CONNECTED,
            exchange=EXCHANGE_OK_NO_MIX,
            account_meta={"status": "ok", "version": "a1"},
            authoritative_current=AUTHORITATIVE_CURRENT,
        )
        second = build_decision_observatory_snapshot(
            trend_quant=TREND_L5_L3,
            eth_btc=ETH_BTC_CONFIRMED,
            event_bundle=EVENT_NOT_CONNECTED,
            exchange=EXCHANGE_OK_NO_MIX,
            account_meta={"status": "ok", "version": "a1"},
            authoritative_current=AUTHORITATIVE_CURRENT,
            previous_decision=first["candidate"],
        )
        self.assertEqual(first["decision_key"], second["decision_key"])
        self.assertEqual(first["candidate"]["target_state"], second["candidate"]["target_state"])
        self.assertTrue(second["candidate"]["idempotent"])

    def test_r2_12_bundle_decision_capability(self):
        bundle = build_observatory_bundle(
            btc_klines_by_tf={},
            eth_klines_by_tf={},
            account_data={"positions": [], "positionsState": "FLAT", "assets": []},
            risk_data={"status": "NORMAL"},
            account_meta={"status": "unknown"},
            market_meta={"status": "ok"},
            mode="TESTNET",
        )
        dec = bundle["decision"]
        self.assertEqual(dec["capability"], CAP_DECISION)
        self.assertFalse(dec["live"])
        self.assertIn("left_card", dec)


class LegacySnapshotTests(unittest.TestCase):
    def test_build_decision_snapshot_delegates_to_brain(self):
        trend = build_trend_quant_snapshot(market_meta={"status": "ok"})
        exchange = build_exchange_observation(
            {"positions": [], "positionsState": "FLAT", "assets": []},
            {"status": "NORMAL"},
            {"status": "unknown"},
        )
        dec = build_decision_snapshot(trend, exchange, eth_btc={"blockers": ["VALUE_TRUTH_UNKNOWN"]})
        self.assertEqual(dec["capability"], CAP_DECISION)
        self.assertNotEqual(dec["capability"], CAP_PROPOSED)


if __name__ == "__main__":
    unittest.main()
