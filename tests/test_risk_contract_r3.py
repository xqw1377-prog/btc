"""P3-R3.0 Risk Contract Harness — R3-1~R3-16 acceptance authority."""
from __future__ import annotations

import ast
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from aurora.risk_contract_harness import (  # noqa: E402
    FORBIDDEN_OUTPUT_KEYS,
    HARNESS_KIND,
    assert_risk_monotonicity,
    default_risk_policy,
    evaluate_risk,
    policy_hash,
    scan_forbidden_imports,
)
from tests.fixtures.risk_contract_r3_cases import (  # noqa: E402
    ALL_R3_CASES,
    R3_1,
    R3_10,
    R3_11,
    R3_12,
    R3_2,
    R3_3,
    R3_4,
    R3_5,
    R3_6_CLOSE,
    R3_6_OPEN,
    R3_7,
    R3_8,
    R3_9,
    R3_KILL,
)

HARNESS_PATH = os.path.join(ROOT, "aurora", "risk_contract_harness.py")


def _eval(case: dict, **extra):
    pol = default_risk_policy()
    if case.get("policy_override"):
        pol.update(case["policy_override"])
    return evaluate_risk(
        case["candidate"],
        case["truth"],
        pol,
        sizing_context=extra.get("sizing") or case.get("sizing_low"),
        previous_plan=extra.get("previous_plan"),
    )


def _dump(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


class IntegrityTests(unittest.TestCase):
    def test_r3_15_no_forbidden_imports(self):
        hits = scan_forbidden_imports(HARNESS_PATH)
        self.assertEqual(hits, [], msg=f"risk_contract_harness imports {hits}")
        with open(HARNESS_PATH, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        modules = [
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        ]
        for banned in ("risk_gate", "portfolio_brain_v2", "risk_kernel", "execution"):
            self.assertFalse(any(banned in (m or "") for m in modules))

    def test_r3_15_no_forbidden_output(self):
        out = _eval(R3_4)
        blob = json.dumps(out)
        for key in FORBIDDEN_OUTPUT_KEYS:
            self.assertNotIn(f'"{key}"', blob)
        self.assertFalse(out["submit_allowed"])
        self.assertEqual(out["runtime_kind"], HARNESS_KIND)


class R3AcceptanceTests(unittest.TestCase):
    def test_r3_1_btc_nav_unknown_blocks_new_risk(self):
        out = _eval(R3_1)
        self.assertIn("BTC_NAV_UNKNOWN", out["blockers"])
        self.assertIn(out["risk_state"], ("BLOCK_NEW_RISK", "UNKNOWN"))
        self.assertFalse(out["new_risk_allowed"])
        self.assertEqual(out["crypto_beta_cluster"]["allowed"]["total"], 0.0)

    def test_r3_2_drawdown_unknown_blocks_new_risk(self):
        out = _eval(R3_2)
        self.assertIn("DRAWDOWN_TRUTH_UNKNOWN", out["blockers"])
        self.assertEqual(out["risk_state"], "BLOCK_NEW_RISK")

    def test_r3_3_brain_request_capped_by_risk(self):
        out = _eval(R3_3)
        req = out["crypto_beta_cluster"]["requested"]["total"]
        alw = out["crypto_beta_cluster"]["allowed"]["total"]
        self.assertGreater(req, 0.006)
        self.assertLessEqual(alw, 0.006 + 1e-9)
        self.assertEqual(out["risk_state"], "REDUCED")

    def test_r3_4_crypto_beta_cluster_joint(self):
        out = _eval(R3_4)
        req = out["crypto_beta_cluster"]["requested"]
        alw = out["crypto_beta_cluster"]["allowed"]
        self.assertGreater(req["btc"], 0)
        self.assertGreater(req["eth"], 0)
        self.assertLessEqual(alw["total"], req["total"] + 1e-9)
        self.assertEqual(out["crypto_beta_cluster"]["state"], "CLUSTERED")

    def test_r3_5_event_increment_unified_budget(self):
        out = _eval(R3_5)
        cluster_alw = out["crypto_beta_cluster"]["allowed"]["total"]
        event_req = out["event_increment"]["requested"]
        event_alw = out["event_increment"]["allowed"]
        if event_req > 0:
            self.assertLessEqual(event_alw, event_req + 1e-9)
            cap = default_risk_policy()["cluster_loss_budget"]
            self.assertLessEqual(cluster_alw + event_alw, cap + default_risk_policy()["event_increment_budget"] + 1e-6)

    def test_r3_6_funding_unknown_blocks_open_not_close(self):
        open_out = _eval(R3_6_OPEN)
        self.assertIn("FUNDING_TRUTH_UNKNOWN", open_out["blockers"])
        self.assertEqual(open_out["crypto_beta_cluster"]["allowed"]["total"], 0.0)
        close_out = _eval(R3_6_CLOSE)
        self.assertTrue(close_out["defensive_reduction_preserved"])

    def test_r3_7_spread_stale_blocks_new_overlay(self):
        out = _eval(R3_7)
        self.assertIn("MARKET_COST_STALE", out["blockers"])
        self.assertEqual(out["crypto_beta_cluster"]["allowed"]["total"], 0.0)

    def test_r3_8_defensive_survives_open_block(self):
        out = _eval(R3_8)
        self.assertTrue(out["defensive_reduction_preserved"])
        self.assertIn(out["risk_state"], ("DEFENSIVE_ONLY", "BLOCK_NEW_RISK"))

    def test_r3_9_position_unknown_defensive_delta_unavailable(self):
        out = _eval(R3_9)
        self.assertTrue(out["defensive_reduction_preserved"])
        self.assertEqual(out["risk_adjusted_delta"]["status"], "UNAVAILABLE")
        self.assertIn("POSITION_TRUTH_UNKNOWN_DEFENSIVE_DELTA_UNAVAILABLE", out["blockers"])

    def test_r3_10_proposed_stop_blocks_new_overlay(self):
        out = _eval(R3_10)
        self.assertIn("STOP_PLAN_NOT_AUTHORITATIVE", out["blockers"])
        self.assertEqual(out["crypto_beta_cluster"]["allowed"]["total"], 0.0)

    def test_r3_11_unit_loss_increase_reduces_q_allowed(self):
        low = evaluate_risk(
            R3_11["candidate"],
            R3_11["truth"],
            default_risk_policy(),
            sizing_context=R3_11["sizing_low"],
        )
        high = evaluate_risk(
            R3_11["candidate"],
            R3_11["truth"],
            default_risk_policy(),
            sizing_context=R3_11["sizing_high"],
        )
        q_low = low["sizing_at_stop"]["q_allowed"]
        q_high = high["sizing_at_stop"]["q_allowed"]
        self.assertIsNotNone(q_low)
        self.assertIsNotNone(q_high)
        self.assertLessEqual(q_high, q_low + 1e-9)

    def test_r3_12_policy_null_fail_closed(self):
        out = _eval(R3_12)
        self.assertTrue(any("RISK_POLICY_NULL" in b for b in out["blockers"]))
        self.assertEqual(out["risk_state"], "UNKNOWN")
        self.assertFalse(out["new_risk_allowed"])

    def test_r3_13_deterministic_and_idempotent(self):
        a = _eval(R3_4)
        b = _eval(R3_4)
        self.assertEqual(_dump(a), _dump(b))
        c = _eval(R3_4, previous_plan=a)
        self.assertTrue(c["idempotent"])
        self.assertEqual(a["risk_plan_key"], c["risk_plan_key"])

    def test_r3_14_risk_plan_key_changes_with_versions(self):
        base = _eval(R3_4)
        alt_truth = dict(R3_4["truth"])
        alt_truth["account_truth"] = {**alt_truth["account_truth"], "version": "acc-v2"}
        alt = evaluate_risk(R3_4["candidate"], alt_truth, default_risk_policy())
        self.assertNotEqual(base["risk_plan_key"], alt["risk_plan_key"])

    def test_r3_kill_active_blocks_new_preserves_defensive(self):
        out = _eval(R3_KILL)
        self.assertIn("KILL_ACTIVE", out["blockers"])
        self.assertFalse(out["new_risk_allowed"])
        self.assertIn("NEW_RISK_ALLOWED=FALSE", out["constraints"])

    def test_r3_16_monotonicity_all_fixtures(self):
        for case in ALL_R3_CASES:
            if case.get("policy_override", {}).get("cluster_loss_budget") is None and case is R3_12:
                out = _eval(case)
            else:
                out = _eval(case)
            violations = assert_risk_monotonicity(out)
            self.assertEqual(violations, [], msg=f"{case['case_id']}: {violations}")


if __name__ == "__main__":
    unittest.main()
