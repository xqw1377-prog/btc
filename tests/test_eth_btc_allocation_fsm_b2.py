"""P2-B.2 allocation FSM — B1–B9 contract acceptance authority."""
from __future__ import annotations

import ast
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from aurora.eth_btc_allocation_fsm import (  # noqa: E402
    ELIGIBILITY_SIGNALS,
    FORBIDDEN_OUTPUT_KEYS,
    HARNESS_KIND,
    evaluate_allocation_fsm,
    compute_state_transition_key,
)
from aurora.eth_btc_value_truth import LookaheadViolation  # noqa: E402
from tests.fixtures.eth_btc_allocation_b2_cases import (  # noqa: E402
    ALL_B_CASES,
    B1_ETH_CHEAP_L1,
    B2_ETH_CHEAP_L3_IMPROVING,
    B3_ETH_WEAKENING,
    B4_THESIS_INVALIDATED,
    B5_VALUE_UNKNOWN,
    B6_VALUE_STALE,
    B7_SAME_EVIDENCE,
    B8_LOOKAHEAD_FIELD,
    B9_INCREASE_NO_TARGET,
)


def _dump(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


class HarnessIntegrityTests(unittest.TestCase):
    def test_no_execution_imports(self):
        path = os.path.join(ROOT, "aurora", "eth_btc_allocation_fsm.py")
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
                self.fail(f"FSM imports forbidden module: {imp}")

    def test_deterministic(self):
        for case in ALL_B_CASES:
            if case["case_id"] == "B8":
                continue
            a = evaluate_allocation_fsm(case)
            b = evaluate_allocation_fsm(case)
            self.assertEqual(_dump(a), _dump(b))

    def test_no_forbidden_output_keys(self):
        for case in ALL_B_CASES:
            if case["case_id"] == "B8":
                continue
            out = evaluate_allocation_fsm(case)
            for key in FORBIDDEN_OUTPUT_KEYS:
                self.assertNotIn(key, out)
            self.assertEqual(out["harness_kind"], HARNESS_KIND)


class B1Tests(unittest.TestCase):
    def test_cheap_l1_watch_no_reallocation(self):
        out = evaluate_allocation_fsm(B1_ETH_CHEAP_L1)
        self.assertEqual(out["state"], "ETH_CANDIDATE")
        self.assertEqual(out["allocation_signal"], "WATCH_ETH")
        self.assertNotIn("INCREASE_ETH_ELIGIBLE", out["allocation_signal"])


class B2Tests(unittest.TestCase):
    def test_cheap_l3_confirmed_increase_eligible(self):
        out = evaluate_allocation_fsm(B2_ETH_CHEAP_L3_IMPROVING)
        self.assertEqual(out["state"], "ETH_CONFIRMED")
        self.assertEqual(out["allocation_signal"], "INCREASE_ETH_ELIGIBLE")


class B3Tests(unittest.TestCase):
    def test_weakening_reduce_eligible(self):
        out = evaluate_allocation_fsm(B3_ETH_WEAKENING)
        self.assertEqual(out["state"], "ETH_WEAKENING")
        self.assertEqual(out["allocation_signal"], "REDUCE_ETH_ELIGIBLE")


class B4Tests(unittest.TestCase):
    def test_thesis_invalidated_btc_return(self):
        out = evaluate_allocation_fsm(B4_THESIS_INVALIDATED)
        self.assertEqual(out["state"], "BTC_RETURN")
        self.assertEqual(out["allocation_signal"], "RETURN_BTC_ELIGIBLE")


class B5Tests(unittest.TestCase):
    def test_unknown_no_reallocation_not_btc_return(self):
        out = evaluate_allocation_fsm(B5_VALUE_UNKNOWN)
        self.assertEqual(out["allocation_signal"], "NO_REALLOCATION")
        self.assertEqual(out["state"], "ETH_HOLD")
        self.assertNotEqual(out["state"], "BTC_RETURN")
        self.assertIn("VALUE_TRUTH_UNKNOWN", out["blockers"])


class B6Tests(unittest.TestCase):
    def test_stale_blocks_new_not_force_sell(self):
        out = evaluate_allocation_fsm(B6_VALUE_STALE)
        self.assertIn("BLOCK_NEW_REALLOCATION", out["blockers"])
        self.assertEqual(out["state"], "ETH_HOLD")
        self.assertEqual(out["allocation_signal"], "HOLD_ETH")
        self.assertNotEqual(out["allocation_signal"], "RETURN_BTC_ELIGIBLE")


class B7Tests(unittest.TestCase):
    def test_idempotent_no_duplicate_eligibility(self):
        case = dict(B7_SAME_EVIDENCE)
        key = compute_state_transition_key(
            case["value"], case["btc_trend"], case["eth_trend"],
            policy_hash=case["policy_hash"],
        )
        case["previous_state"] = {
            "state": "ETH_CONFIRMED",
            "allocation_signal": "INCREASE_ETH_ELIGIBLE",
            "state_transition_key": key,
        }
        out = evaluate_allocation_fsm(case)
        self.assertTrue(out["idempotent"])
        self.assertEqual(out["state"], "ETH_CONFIRMED")
        self.assertEqual(out["allocation_signal"], "NO_REALLOCATION")
        self.assertIn("IDEMPOTENT_EVIDENCE", out["blockers"])


class B8Tests(unittest.TestCase):
    def test_lookahead_rejected(self):
        with self.assertRaises(LookaheadViolation):
            evaluate_allocation_fsm(B8_LOOKAHEAD_FIELD)


class B9Tests(unittest.TestCase):
    def test_increase_has_no_target_weight(self):
        out = evaluate_allocation_fsm(B9_INCREASE_NO_TARGET)
        self.assertEqual(out["allocation_signal"], "INCREASE_ETH_ELIGIBLE")
        for key in FORBIDDEN_OUTPUT_KEYS:
            self.assertNotIn(key, out)


if __name__ == "__main__":
    unittest.main()
