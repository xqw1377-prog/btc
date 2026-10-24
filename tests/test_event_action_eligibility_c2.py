"""P2-C.2 Event Action Eligibility — C2-1..C2-12 acceptance authority."""
from __future__ import annotations

import ast
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from aurora.event_action_eligibility import (  # noqa: E402
    ACTIVE_UNREACHABLE,
    FORBIDDEN_OUTPUT_KEYS,
    HARNESS_KIND,
    LookaheadViolation,
    assess_action_eligibility,
    assess_impact,
    assess_priced_in,
    evaluate_event_eligibility,
    get_event_class_policies,
    _eligibility_fingerprint,
)
from tests.fixtures.event_action_eligibility_c2_cases import (  # noqa: E402
    ALL_C2_CASES,
    C2_1_E0_RUMOR,
    C2_10_IDEMPOTENT,
    C2_11_LOOKAHEAD,
    C2_2_E1_UNKNOWN_DIR,
    C2_3_PRICED_IN_MOST,
    C2_4_BOOST_ELIGIBLE,
    C2_5_TREND_L1,
    C2_6_PRICED_IN_UNKNOWN,
    C2_7_RISK_OFF_L5,
    C2_8_RETRACTED,
    C2_9_STALE,
    SEC_SOCIAL_FAKE_ETF,
    T_AS_OF_MS,
)


def _dump(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


def _eval(case: dict) -> dict:
    return evaluate_event_eligibility(case)


class IntegrityTests(unittest.TestCase):
    def test_no_execution_imports(self):
        path = os.path.join(ROOT, "aurora", "event_action_eligibility.py")
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imports = [
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        ]
        banned = ("binance", "trading_cycle", "risk_gate", "execution")
        for imp in imports:
            if imp and any(b in imp for b in banned):
                self.fail(f"event_action_eligibility imports forbidden: {imp}")

    def test_event_class_policy_registry(self):
        policies = get_event_class_policies()
        required = {
            "FED_RATE_DECISION",
            "CPI_RELEASE",
            "NFP_RELEASE",
            "SEC_CRYPTO_REGULATION",
            "ETF_APPROVAL_REJECTION",
            "MAJOR_EXCHANGE_FAILURE",
            "SYSTEMIC_HACK",
        }
        self.assertTrue(required.issubset(set(policies.keys())))

    def test_deterministic(self):
        for case in ALL_C2_CASES:
            if case["case_id"] == "C2-11":
                continue
            a = _eval(case)
            b = _eval(case)
            self.assertEqual(_dump(a), _dump(b))

    def test_c2_12_no_forbidden_output_keys(self):
        for case in ALL_C2_CASES:
            if case["case_id"] == "C2-11":
                continue
            out = _eval(case)
            blob = json.dumps(out)
            for key in FORBIDDEN_OUTPUT_KEYS:
                self.assertNotIn(f'"{key}"', blob, msg=f"{case['case_id']} leaked {key}")


class C2AcceptanceTests(unittest.TestCase):
    def test_c2_1_e0_rumor_watch(self):
        out = _eval(C2_1_E0_RUMOR)
        elig = out["event_action_eligibility"]
        self.assertEqual(elig["action_state"], "WATCH")
        self.assertIn(elig["boost_eligibility"], ("WATCH_ONLY", "NO_BOOST"))
        self.assertEqual(out["event_impact_assessment"]["evidence_grade"], "E0")

    def test_c2_2_e1_confirmed_no_boost(self):
        out = _eval(C2_2_E1_UNKNOWN_DIR)
        elig = out["event_action_eligibility"]
        self.assertEqual(elig["action_state"], "CONFIRMED")
        self.assertEqual(elig["boost_eligibility"], "CONFIRMED_FACT")
        self.assertEqual(out["event_impact_assessment"]["evidence_grade"], "E1")

    def test_c2_3_priced_in_most_no_boost(self):
        out = _eval(C2_3_PRICED_IN_MOST)
        elig = out["event_action_eligibility"]
        self.assertEqual(out["priced_in_assessment"]["priced_in"], "MOST")
        self.assertEqual(elig["boost_eligibility"], "NO_BOOST")
        self.assertEqual(elig["action_state"], "CONFIRMED")

    def test_c2_4_event_boost_eligible(self):
        out = _eval(C2_4_BOOST_ELIGIBLE)
        elig = out["event_action_eligibility"]
        self.assertEqual(out["event_impact_assessment"]["evidence_grade"], "E3")
        self.assertEqual(out["priced_in_assessment"]["priced_in"], "PARTIAL")
        self.assertEqual(elig["action_state"], "ELIGIBLE")
        self.assertEqual(elig["boost_eligibility"], "EVENT_BOOST_ELIGIBLE")
        self.assertEqual(elig["event_increment_request"], "ELIGIBLE")
        self.assertEqual(elig["active_unreachable"], ACTIVE_UNREACHABLE)

    def test_c2_5_trend_l1_no_boost(self):
        out = _eval(C2_5_TREND_L1)
        elig = out["event_action_eligibility"]
        self.assertEqual(elig["action_state"], "CONFIRMED")
        self.assertEqual(elig["boost_eligibility"], "NO_BOOST")
        self.assertIn("TREND_NOT_CONFIRMED", elig["blockers"])

    def test_c2_6_priced_in_unknown_no_boost(self):
        out = _eval(C2_6_PRICED_IN_UNKNOWN)
        elig = out["event_action_eligibility"]
        self.assertEqual(out["priced_in_assessment"]["priced_in"], "UNKNOWN")
        self.assertEqual(elig["boost_eligibility"], "NO_BOOST")
        self.assertIn("PRICED_IN_UNKNOWN", elig["blockers"])

    def test_c2_7_risk_off_no_short(self):
        out = _eval(C2_7_RISK_OFF_L5)
        elig = out["event_action_eligibility"]
        self.assertEqual(elig["action_state"], "RISK_OFF")
        self.assertEqual(elig["boost_eligibility"], "RISK_OFF_ELIGIBLE")
        self.assertIn("NO_SHORT_AUTHORITY", elig["blockers"])
        self.assertTrue(len(elig["risk_off_overlays"]) >= 1)
        self.assertNotIn("open_short", json.dumps(out).lower())

    def test_c2_8_retracted_none(self):
        out = _eval(C2_8_RETRACTED)
        elig = out["event_action_eligibility"]
        self.assertEqual(elig["action_state"], "NONE")
        self.assertEqual(elig["boost_eligibility"], "NONE")
        self.assertIn("EVENT_RETRACTED", elig["blockers"])

    def test_c2_9_stale_no_boost(self):
        out = _eval(C2_9_STALE)
        elig = out["event_action_eligibility"]
        self.assertEqual(elig["boost_eligibility"], "NO_BOOST")
        self.assertIn("FRESHNESS_STALE", elig["blockers"])

    def test_c2_10_idempotent(self):
        case = dict(C2_10_IDEMPOTENT)
        impact = assess_impact(case["event_truth"])
        priced = assess_priced_in(case["event_truth"], case["market_context"])
        fp = _eligibility_fingerprint(
            case["event_truth"], impact, priced,
            {"btc": case["btc_trend_snapshot"], "eth": case["eth_trend_snapshot"]},
        )
        case["previous_event_state"] = {
            "fingerprint": fp,
            "action_state": "CONFIRMED",
        }
        out = _eval(case)
        elig = out["event_action_eligibility"]
        self.assertTrue(elig["idempotent"])
        self.assertEqual(elig["boost_eligibility"], "NO_BOOST")
        self.assertIn("IDEMPOTENT", elig["blockers"])

    def test_c2_11_lookahead_rejected(self):
        with self.assertRaises(LookaheadViolation):
            _eval(C2_11_LOOKAHEAD)

    def test_sec_social_fake_etf_never_boost(self):
        out = _eval(SEC_SOCIAL_FAKE_ETF)
        elig = out["event_action_eligibility"]
        self.assertEqual(out["event_impact_assessment"]["evidence_grade"], "E0")
        self.assertEqual(elig["action_state"], "WATCH")
        self.assertNotEqual(elig["boost_eligibility"], "EVENT_BOOST_ELIGIBLE")


class LayerSeparationTests(unittest.TestCase):
    def test_three_layers_present(self):
        out = _eval(C2_4_BOOST_ELIGIBLE)
        self.assertEqual(out["harness_kind"], HARNESS_KIND)
        self.assertEqual(out["event_impact_assessment"]["layer"], "C2-A")
        self.assertEqual(out["priced_in_assessment"]["layer"], "C2-B")
        self.assertEqual(out["event_action_eligibility"]["layer"], "C2-C")

    def test_impact_not_probability_flag(self):
        out = _eval(C2_4_BOOST_ELIGIBLE)
        self.assertTrue(out["event_impact_assessment"]["impact_is_not_probability"])

    def test_priced_in_anchor_first_observed(self):
        truth = C2_4_BOOST_ELIGIBLE["event_truth"]
        priced = assess_priced_in(truth, C2_4_BOOST_ELIGIBLE["market_context"])
        self.assertEqual(priced["anchor_time"], truth["first_observed_at"])

    def test_lookahead_post_price_after_as_of(self):
        truth = C2_4_BOOST_ELIGIBLE["event_truth"]
        ctx = dict(C2_4_BOOST_ELIGIBLE["market_context"])
        ctx["post_observation_ms"] = T_AS_OF_MS + 999_999
        with self.assertRaises(LookaheadViolation):
            assess_priced_in(truth, ctx, as_of_ms=T_AS_OF_MS)


if __name__ == "__main__":
    unittest.main()
