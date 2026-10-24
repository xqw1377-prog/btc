"""Decision Brain V1.1 contract harness — T1–T8 + A1 guards (T9/T10).

CONTRACT HARNESS ONLY · NOT P3 · NOT EXECUTION.
"""
from __future__ import annotations

import ast
import importlib
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from aurora.decision_brain_harness import (  # noqa: E402
    FORBIDDEN_OUTPUT_KEYS,
    HARNESS_KIND,
    evaluate_contract,
    evaluate_pre_submit_revalidation,
    evaluate_protection_authority,
)
from tests.fixtures.decision_brain_v1_1_cases import (  # noqa: E402
    ALL_T_CASES,
    T1_ETH_CHEAP_L1,
    T10_PROTECTION_ACK_ONLY,
    T2_BTC_L4_ETH_L4,
    T3_TREND_EVENT_SAME_DIR,
    T4_APLUS_EVENT_L1,
    T5_ACCOUNT_UNKNOWN,
    T6_CLOSE_WHILE_OPEN_BLOCKED,
    T7_EVENT_RETRACTED,
    T8_FRESH_EVIDENCE,
    T8_STOP_OLD_EVIDENCE,
    T9_PLAN_SNAPSHOT,
    T9_SUBMIT_SNAPSHOT_DRIFT,
)


def _dump(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


class HarnessIntegrityTests(unittest.TestCase):
    def test_harness_module_has_no_execution_imports(self):
        path = os.path.join(ROOT, "aurora", "decision_brain_harness.py")
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imports = [
            node.names[0].name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for _ in [node]
        ] + [
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        ]
        banned = ("binance", "trading_cycle", "risk_gate", "execution")
        for imp in imports:
            if imp and any(b in imp for b in banned):
                self.fail(f"harness imports forbidden module: {imp}")

    def test_output_never_contains_forbidden_keys(self):
        for case in ALL_T_CASES:
            out = evaluate_contract(case)
            for key in FORBIDDEN_OUTPUT_KEYS:
                self.assertNotIn(key, out)
            self.assertEqual(out["harness_kind"], HARNESS_KIND)

    def test_deterministic_same_input_same_output(self):
        for case in ALL_T_CASES:
            a = evaluate_contract(case)
            b = evaluate_contract(case)
            self.assertEqual(_dump(a), _dump(b))

    def test_target_delta_not_order_execution(self):
        out = evaluate_contract(T2_BTC_L4_ETH_L4)
        self.assertIn("target_state", out)
        self.assertIn("delta_proposal", out)
        self.assertNotIn("order", out)
        self.assertNotIn("execution", out)
        self.assertFalse(out["submit_allowed"])


class T1Tests(unittest.TestCase):
    def test_eth_cheap_l1_watch_no_reallocation(self):
        out = evaluate_contract(T1_ETH_CHEAP_L1)
        self.assertEqual(out["allocation_signal"], "WATCH_ETH")
        self.assertEqual(out["spot_action"], "NO_REALLOCATION")
        self.assertEqual(out["delta_proposal"]["spot_btc"], 0.0)
        self.assertEqual(out["delta_proposal"]["spot_eth"], 0.0)


class T2Tests(unittest.TestCase):
    def test_beta_cluster_cap_not_full_per_trade_each(self):
        out = evaluate_contract(T2_BTC_L4_ETH_L4)
        cluster = out["cluster_overlay_risk"]
        per_trade = cluster["per_trade_cap"]
        self.assertLessEqual(cluster["total"], cluster["cluster_cap"] + 1e-9)
        self.assertLess(cluster["btc"], per_trade)
        self.assertLess(cluster["eth"], per_trade)
        self.assertGreater(cluster["btc"], 0)
        self.assertGreater(cluster["eth"], 0)


class T3Tests(unittest.TestCase):
    def test_event_incremental_not_double_count(self):
        out = evaluate_contract(T3_TREND_EVENT_SAME_DIR)
        base = out["cluster_overlay_risk"]["total"]
        inc = out["event_increment_budget"]
        self.assertGreater(inc, 0)
        self.assertLessEqual(base + inc, out["cluster_overlay_risk"]["cluster_cap"] + inc + 1e-9)
        self.assertIn("incremental", " ".join(out["reasons"]).lower())


class T4Tests(unittest.TestCase):
    def test_aplus_event_l1_no_boost(self):
        out = evaluate_contract(T4_APLUS_EVENT_L1)
        self.assertEqual(out["event_increment_budget"], 0.0)
        self.assertEqual(out["target_state"]["event_increment_risk"], 0.0)


class T5Tests(unittest.TestCase):
    def test_unknown_account_blocks_new_risk(self):
        out = evaluate_contract(T5_ACCOUNT_UNKNOWN)
        self.assertTrue(out["block_new_risk"])
        self.assertTrue(any("P0" in b for b in out["blockers"]))


class T6Tests(unittest.TestCase):
    def test_close_allowed_when_open_blocked(self):
        out = evaluate_contract(T6_CLOSE_WHILE_OPEN_BLOCKED)
        self.assertTrue(out["block_new_risk"])
        self.assertTrue(out["close_allowed"])
        self.assertTrue(out["reduce_allowed"])
        self.assertEqual(out["overlay_action"], "CLOSE_OVERLAY")
        self.assertEqual(out["target_state"]["overlay"]["btc"], 0.0)


class T7Tests(unittest.TestCase):
    def test_retracted_removes_increment_no_reverse(self):
        out = evaluate_contract(T7_EVENT_RETRACTED)
        self.assertEqual(out["target_state"]["event_increment_risk"], 0.0)
        self.assertEqual(out["event_increment_budget"], 0.0)
        delta = out["delta_proposal"]
        self.assertLess(delta["event_increment_risk"], 0)
        self.assertGreaterEqual(out["target_state"]["overlay"]["btc"], 0)


class T8Tests(unittest.TestCase):
    def test_old_evidence_no_reentry(self):
        out = evaluate_contract(T8_STOP_OLD_EVIDENCE)
        self.assertEqual(out["rearm_state"], "DISARMED")
        self.assertTrue(any("NO REENTRY" in b for b in out["blockers"]))

    def test_fresh_evidence_rearm(self):
        out = evaluate_contract(T8_FRESH_EVIDENCE)
        self.assertEqual(out["rearm_state"], "RE_ARM")


class ContractGuardTests(unittest.TestCase):
    def test_t9_plan_expired_on_account_version_drift(self):
        plan = {"open_iff_pass": True, **T9_PLAN_SNAPSHOT}
        result = evaluate_pre_submit_revalidation(plan, T9_SUBMIT_SNAPSHOT_DRIFT)
        self.assertEqual(result["pre_submit_revalidation"], "PLAN_EXPIRED")
        self.assertEqual(result["action"], "RECOMPUTE")
        self.assertFalse(result["submit_allowed"])
        self.assertIn("account_snapshot_version", result["changed_fields"])

    def test_t9_pass_when_versions_match(self):
        result = evaluate_pre_submit_revalidation(T9_PLAN_SNAPSHOT, T9_PLAN_SNAPSHOT)
        self.assertEqual(result["pre_submit_revalidation"], "PASS")

    def test_t10_ack_not_active_stop(self):
        result = evaluate_protection_authority(T10_PROTECTION_ACK_ONLY)
        self.assertEqual(result["protection_state"], "ACK_ONLY")
        self.assertFalse(result["is_active_stop"])
        self.assertNotEqual(result["protection_state"], "ACTIVE")

    def test_approved_not_submitted_in_harness(self):
        out = evaluate_contract(T2_BTC_L4_ETH_L4)
        self.assertFalse(out["submit_allowed"])
        prot = evaluate_protection_authority(T10_PROTECTION_ACK_ONLY)
        self.assertTrue(prot["proposed_stop"])
        self.assertFalse(prot["is_active_stop"])


class AllCasesSmokeTests(unittest.TestCase):
    def test_all_t_cases_evaluate_without_error(self):
        for case in ALL_T_CASES:
            out = evaluate_contract(case)
            self.assertEqual(out["case_id"], case["case_id"])
            self.assertIn("target_state", out)
            self.assertIn("delta_proposal", out)


if __name__ == "__main__":
    unittest.main()
