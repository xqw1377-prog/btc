"""P2-C.0 Event Intelligence contract harness — C1–C10 acceptance authority."""
from __future__ import annotations

import ast
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from aurora.event_intelligence_harness import (  # noqa: E402
    ACTIVE_UNREACHABLE,
    FORBIDDEN_OUTPUT_KEYS,
    HARNESS_KIND,
    LookaheadViolation,
    compute_evidence_version,
    evaluate_event_contract,
)
from tests.fixtures.event_intelligence_c0_cases import (  # noqa: E402
    ALL_C_CASES,
    C1_UNVERIFIED_RUMOR,
    C2_OFFICIAL_NO_DIRECTION,
    C3_PRICED_IN_MOST,
    C4_ELIGIBLE_BOOST,
    C5_E3_TREND_L1,
    C6_UNKNOWN_CLASS,
    C7_RETRACTED,
    C8_IDEMPOTENT,
    C9_SINGLE_CLUSTER,
)


def _dump(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


class HarnessIntegrityTests(unittest.TestCase):
    def test_no_execution_imports(self):
        path = os.path.join(ROOT, "aurora", "event_intelligence_harness.py")
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
                self.fail(f"event harness imports forbidden module: {imp}")

    def test_deterministic(self):
        for case in ALL_C_CASES:
            a = evaluate_event_contract(case)
            b = evaluate_event_contract(case)
            self.assertEqual(_dump(a), _dump(b))

    def test_no_forbidden_output_keys(self):
        for case in ALL_C_CASES:
            out = evaluate_event_contract(case)
            for key in FORBIDDEN_OUTPUT_KEYS:
                self.assertNotIn(key, out)
                self.assertNotIn(key, out.get("event_context", {}))
            self.assertEqual(out["harness_kind"], HARNESS_KIND)

    def test_active_unreachable(self):
        out = evaluate_event_contract(C4_ELIGIBLE_BOOST)
        self.assertEqual(
            out["event_action_eligibility"]["active_unreachable"],
            ACTIVE_UNREACHABLE,
        )
        self.assertEqual(out["event_context"]["active_policy"], ACTIVE_UNREACHABLE)


class C1Tests(unittest.TestCase):
    def test_unverified_rumor_e0_watch(self):
        out = evaluate_event_contract(C1_UNVERIFIED_RUMOR)
        self.assertEqual(out["event_context"]["evidence_grade"], "E0")
        self.assertEqual(out["event_context"]["action_state"], "WATCH")
        self.assertIn(out["event_context"]["boost_eligibility"], ("WATCH_ONLY", "NONE", "NO_BOOST"))


class C2Tests(unittest.TestCase):
    def test_official_no_direction_e1(self):
        out = evaluate_event_contract(C2_OFFICIAL_NO_DIRECTION)
        self.assertEqual(out["event_context"]["evidence_grade"], "E1")
        self.assertEqual(out["event_context"]["action_state"], "CONFIRMED")
        self.assertEqual(out["event_context"]["boost_eligibility"], "CONFIRMED_FACT")


class C3Tests(unittest.TestCase):
    def test_priced_in_most_no_boost(self):
        out = evaluate_event_contract(C3_PRICED_IN_MOST)
        self.assertNotEqual(out["event_context"]["boost_eligibility"], "EVENT_BOOST_ELIGIBLE")
        self.assertEqual(out["event_context"]["boost_eligibility"], "NO_BOOST")
        self.assertIn("PRICED_IN_MOST", out["blockers"])


class C4Tests(unittest.TestCase):
    def test_e3_l4_partial_eligible(self):
        out = evaluate_event_contract(C4_ELIGIBLE_BOOST)
        self.assertEqual(out["event_context"]["evidence_grade"], "E3")
        self.assertEqual(out["event_context"]["action_state"], "ELIGIBLE")
        self.assertEqual(out["event_context"]["boost_eligibility"], "EVENT_BOOST_ELIGIBLE")


class C5Tests(unittest.TestCase):
    def test_e3_l1_confirmed_no_boost(self):
        out = evaluate_event_contract(C5_E3_TREND_L1)
        self.assertEqual(out["event_context"]["evidence_grade"], "E3")
        self.assertEqual(out["event_context"]["action_state"], "CONFIRMED")
        self.assertEqual(out["event_context"]["boost_eligibility"], "NO_BOOST")
        self.assertIn("TREND_NOT_CONFIRMED", out["blockers"])


class C6Tests(unittest.TestCase):
    def test_unknown_class_never_eligible(self):
        out = evaluate_event_contract(C6_UNKNOWN_CLASS)
        self.assertNotEqual(out["event_context"]["action_state"], "ELIGIBLE")
        self.assertNotEqual(out["event_context"]["boost_eligibility"], "EVENT_BOOST_ELIGIBLE")
        self.assertIn("UNKNOWN_EVENT_CLASS", out["blockers"])


class C7Tests(unittest.TestCase):
    def test_retracted_removes_eligibility(self):
        out = evaluate_event_contract(C7_RETRACTED)
        self.assertEqual(out["event_context"]["action_state"], "NONE")
        self.assertEqual(out["event_context"]["boost_eligibility"], "NO_BOOST")
        self.assertIn("EVENT_RETRACTED", out["blockers"])
        self.assertNotIn("OPEN SHORT", str(out).upper())


class C8Tests(unittest.TestCase):
    def test_idempotent_no_duplicate_boost(self):
        case = dict(C8_IDEMPOTENT)
        ver = compute_evidence_version(case["event_record"], case["assessment"])
        case["previous_context"] = {
            "event_id": "evt-c8",
            "evidence_version": ver,
            "action_state": "ELIGIBLE",
            "boost_eligibility": "EVENT_BOOST_ELIGIBLE",
        }
        out = evaluate_event_contract(case)
        self.assertTrue(out["idempotent"])
        self.assertEqual(out["event_context"]["boost_eligibility"], "NO_BOOST")
        self.assertIn("IDEMPOTENT_EVIDENCE", out["blockers"])


class C9Tests(unittest.TestCase):
    def test_reposts_single_cluster(self):
        out = evaluate_event_contract(C9_SINGLE_CLUSTER)
        self.assertEqual(out["event_context"]["corroboration_count"], 1)


class C10Tests(unittest.TestCase):
    def test_lookahead_rejected(self):
        case = dict(C4_ELIGIBLE_BOOST)
        case["ex_post_revision"] = "2026-09-12 revised CPI"
        with self.assertRaises(LookaheadViolation):
            evaluate_event_contract(case)


class E3NotTradeTests(unittest.TestCase):
    def test_e3_alone_not_eligible_without_gates(self):
        case = dict(C4_ELIGIBLE_BOOST)
        case["trend"] = {"btc": {"level": "L1/5"}}
        out = evaluate_event_contract(case)
        self.assertNotEqual(out["event_context"]["boost_eligibility"], "EVENT_BOOST_ELIGIBLE")


class NegativeEventTests(unittest.TestCase):
    def test_e3_negative_max_risk_off_not_short(self):
        case = dict(C4_ELIGIBLE_BOOST)
        case["assessment"] = {
            **case["assessment"],
            "direction_btc": "NEGATIVE",
            "impact_btc": -4,
            "evidence_grade": "E3",
        }
        out = evaluate_event_contract(case)
        self.assertEqual(out["event_context"]["action_state"], "RISK_OFF")
        self.assertEqual(out["event_context"]["boost_eligibility"], "RISK_OFF_ELIGIBLE")
        self.assertIn("NO_SHORT_AUTHORITY", out["blockers"])


if __name__ == "__main__":
    unittest.main()
