"""P2-C.3 Event Observatory Mirror — acceptance authority."""
from __future__ import annotations

import ast
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from aurora.event_observatory import (  # noqa: E402
    CAP_SEMANTICS,
    INGESTION_NOT_CONNECTED,
    build_event_observatory_snapshot,
)
from tests.fixtures.event_observatory_c3_cases import (  # noqa: E402
    ALL_C3_CASES,
    RETRACTION_SCENARIO,
    SCENARIO_A,
    SCENARIO_B,
    SCENARIO_C,
)


FORBIDDEN = frozenset({
    "target_weight", "target_leverage", "order_qty", "submit", "execute", "open_short",
})


class IntegrityTests(unittest.TestCase):
    def test_not_connected_not_no_events(self):
        snap = build_event_observatory_snapshot(official_sources_connected=False)
        self.assertEqual(snap["source_health_summary"], "SOURCE_NOT_CONNECTED")
        self.assertEqual(snap["event_state"], "UNKNOWN")
        self.assertNotEqual(snap["observation_state"], "NO_EVENT_OBSERVED")
        self.assertIn("NOT CONNECTED", snap["left_card"]["headlines"][1])

    def test_source_error_not_empty_calm(self):
        snap = build_event_observatory_snapshot(
            official_sources_connected=True,
            source_fetch_status="error",
        )
        self.assertEqual(snap["source_health_summary"], "SOURCE_ERROR")
        self.assertIsNone(snap["primary_event_id"])
        self.assertNotEqual(snap["observation_state"], "NO_EVENT_OBSERVED")
        self.assertIn("SOURCE ERROR", snap["left_card"]["headlines"][0])

    def test_connected_no_fixture_no_event_observed(self):
        snap = build_event_observatory_snapshot(official_sources_connected=True)
        self.assertEqual(snap["observation_state"], "NO_EVENT_OBSERVED")
        self.assertEqual(snap["decision_events"], "NONE")

    def test_no_forbidden_output_keys(self):
        for case in ALL_C3_CASES:
            snap = build_event_observatory_snapshot(**{
                k: v for k, v in case.items() if k != "case_id"
            })
            blob = json.dumps(snap)
            for key in FORBIDDEN:
                self.assertNotIn(f'"{key}"', blob)

    def test_no_execution_imports(self):
        path = os.path.join(ROOT, "aurora", "event_observatory.py")
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
                self.fail(f"event_observatory imports forbidden: {imp}")


class C3AcceptanceTests(unittest.TestCase):
    def test_c3_backend_left_card_from_snapshot(self):
        snap = build_event_observatory_snapshot(**{
            k: v for k, v in SCENARIO_A.items() if k != "case_id"
        })
        lc = snap["left_card"]
        self.assertIn("NO BOOST", lc["headline_action"])
        self.assertEqual(snap["items"][0]["priced_in"]["priced_in"], "UNKNOWN")
        self.assertEqual(snap["capability"], CAP_SEMANTICS)

    def test_c3_e3_not_auto_eligible(self):
        snap = build_event_observatory_snapshot(**{
            k: v for k, v in SCENARIO_A.items() if k != "case_id"
        })
        item = snap["items"][0]
        if item["impact"]["evidence_grade"] == "E3":
            self.assertNotEqual(
                item["eligibility"]["boost_eligibility"],
                "EVENT_BOOST_ELIGIBLE",
            )

    def test_c3_boost_eligible_scenario_b(self):
        snap = build_event_observatory_snapshot(**{
            k: v for k, v in SCENARIO_B.items() if k != "case_id"
        })
        primary = snap["items"][0]
        self.assertEqual(primary["eligibility"]["boost_eligibility"], "EVENT_BOOST_ELIGIBLE")
        self.assertEqual(snap["left_card"]["headline_action"], "EVENT BOOST ELIGIBLE")
        self.assertIn("ELIGIBLE ≠ ACTIVE", snap["left_card"]["meta"])

    def test_c3_risk_off_no_short(self):
        snap = build_event_observatory_snapshot(**{
            k: v for k, v in SCENARIO_C.items() if k != "case_id"
        })
        primary = snap["items"][0]
        self.assertEqual(primary["eligibility"]["action_state"], "RISK_OFF")
        self.assertIn("NO SHORT AUTHORITY", snap["left_card"]["meta"])
        self.assertNotIn("open_short", json.dumps(snap).lower())

    def test_c3_priced_in_unknown_no_boost(self):
        snap = build_event_observatory_snapshot(**{
            k: v for k, v in SCENARIO_A.items() if k != "case_id"
        })
        self.assertEqual(snap["left_card"]["headline_action"], "NO BOOST")

    def test_c3_retracted_visible(self):
        snap = build_event_observatory_snapshot(**{
            k: v for k, v in RETRACTION_SCENARIO.items() if k != "case_id"
        })
        primary = snap["items"][0]
        self.assertTrue(primary["left"]["retracted"])
        self.assertEqual(primary["eligibility"]["action_state"], "NONE")
        self.assertIn("revoked", (snap["left_card"].get("disclaimer") or "").lower())

    def test_c3_primary_sort_risk_off_over_eligible(self):
        snap = build_event_observatory_snapshot(
            official_sources_connected=True,
            fixture_pipeline=[
                *SCENARIO_B["fixture_pipeline"],
                *SCENARIO_C["fixture_pipeline"],
            ],
            btc_trend=SCENARIO_C["btc_trend"],
            as_of_ms=SCENARIO_C["as_of_ms"],
        )
        self.assertEqual(snap["primary_event_id"], "EXCHANGE_FAIL_2026")

    def test_c3_right_traceability(self):
        snap = build_event_observatory_snapshot(**{
            k: v for k, v in SCENARIO_B.items() if k != "case_id"
        })
        layers = snap["right_evidence"]["layers"]
        self.assertIn("first_observed_at", layers["what_happened"])
        self.assertIn("evidence_grade", layers["evidence"])
        self.assertIsNone(layers["evidence"].get("surprise") if layers["evidence"].get("consensus_truth_state") == "UNKNOWN" else layers["evidence"].get("surprise"))

    def test_c3_ingestion_not_connected_default(self):
        snap = build_event_observatory_snapshot()
        self.assertEqual(snap["official_source_ingestion"], INGESTION_NOT_CONNECTED)


if __name__ == "__main__":
    unittest.main()
