"""P3-R1 Decision Brain Core — R1–R13 acceptance authority."""
from __future__ import annotations

import ast
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from aurora.decision_brain import (  # noqa: E402
    FORBIDDEN_OUTPUT_EXTENDED,
    RUNTIME_KIND,
    build_normalized_decision_input,
    default_decision_policy,
    evaluate_decision,
    policy_hash,
)
from aurora.decision_brain_entry_gate import scan_forbidden_imports  # noqa: E402
from tests.fixtures.decision_brain_r1_cases import (  # noqa: E402
    CURRENT_80_10,
    EVENT_ELIG_SCHEMA,
    EVENT_NC_SCHEMA,
    KNOWN_ACCOUNT,
    PROT_UNKNOWN,
    RISK_OFF_EVENT,
    TREND_L4_SCHEMA,
    TREND_L5,
    TREND_ETH_L3,
    UNKNOWN_ACCOUNT,
    VALUE_CONFIRMED_SCHEMA,
    VALUE_FAIR_SCHEMA,
    _base,
)

BRAIN_PATH = os.path.join(ROOT, "aurora", "decision_brain.py")
FORBIDDEN = FORBIDDEN_OUTPUT_EXTENDED


def _eval(**kw):
    return evaluate_decision(build_normalized_decision_input(**kw))


def _dump(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


class IntegrityTests(unittest.TestCase):
    def test_r12_no_forbidden_imports(self):
        hits = scan_forbidden_imports(BRAIN_PATH)
        self.assertEqual(hits, [], msg=f"decision_brain imports {hits}")
        with open(BRAIN_PATH, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        modules = [
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        ]
        for banned in ("observatory_snapshots", "dashboard_feed", "portfolio_brain_v2"):
            self.assertNotIn(f"aurora.{banned}", modules)

    def test_r12_no_forbidden_output(self):
        out = _eval(**_base())
        blob = json.dumps(out)
        for key in FORBIDDEN:
            self.assertNotIn(f'"{key}"', blob)
        self.assertFalse(out["submit_allowed"])


class R1AcceptanceTests(unittest.TestCase):
    def test_r1_trend_survives_event_not_connected(self):
        out = _eval(**_base())
        self.assertGreater(out["crypto_beta_cluster"]["total_request"], 0)
        self.assertEqual(out["event_increment_request"], "NONE")
        self.assertEqual(out["event_action"], "NONE")

    def test_r2_account_unknown_target_candidate_delta_unavailable(self):
        out = _eval(
            **_base(
                value_input=VALUE_CONFIRMED_SCHEMA,
                account_truth=UNKNOWN_ACCOUNT,
                current_state=None,
            )
        )
        self.assertEqual(out["current_state"]["status"], "UNKNOWN")
        self.assertEqual(out["target_state"]["status"], "CANDIDATE")
        self.assertEqual(out["delta_proposal"]["status"], "UNAVAILABLE")
        self.assertIn("ACCOUNT_TRUTH_UNKNOWN", out["blockers"])

    def test_r3_authoritative_current_delta_deterministic(self):
        out = _eval(
            **_base(
                value_input=VALUE_CONFIRMED_SCHEMA,
                trend_eth={**TREND_ETH_L3, "trend_level": "L4/5"},
                current_state=CURRENT_80_10,
            )
        )
        self.assertEqual(out["delta_proposal"]["status"], "AVAILABLE")
        self.assertAlmostEqual(out["delta_proposal"]["eth"], 10.0, places=4)
        self.assertAlmostEqual(out["delta_proposal"]["btc"], -10.0, places=4)

    def test_r4_crypto_beta_cluster_no_double_full_budget(self):
        out = _eval(**_base())
        c = out["crypto_beta_cluster"]
        per = default_decision_policy()["trend_overlay_caps"]["per_asset_max"]
        self.assertLess(c["btc_request"], per)
        self.assertLess(c["eth_request"], per)
        self.assertLessEqual(c["total_request"], c["cluster_cap"] + 1e-9)

    def test_r5_event_increment_not_double_count(self):
        out = _eval(
            **_base(
                event_input=EVENT_ELIG_SCHEMA,
                trend_eth=TREND_ETH_L3,
            )
        )
        base = out["crypto_beta_cluster"]["total_request"]
        inc = out["target_state"]["event_increment"]
        self.assertEqual(out["event_increment_request"], "ELIGIBLE")
        self.assertGreater(inc, 0)
        self.assertLessEqual(base + inc, out["crypto_beta_cluster"]["cluster_cap"] + inc + 1e-9)

    def test_r6_risk_off_wins_over_bullish_trend(self):
        out = _eval(
            **_base(
                trend_btc=TREND_L5,
                event_input=RISK_OFF_EVENT,
            )
        )
        self.assertEqual(out["event_action"], "RISK_OFF")
        self.assertEqual(out["event_increment_request"], "REMOVE")
        self.assertNotIn("open_short", json.dumps(out).lower())

    def test_r7_close_survives_open_block(self):
        out = _eval(
            **_base(
                account_truth=PROT_UNKNOWN,
                thesis_invalidated=True,
                close_condition=True,
            )
        )
        self.assertTrue(out["close_allowed"])
        self.assertIn(out["btc_overlay_action"], ("CLOSE_OVERLAY", "REDUCE_OR_CLOSE"))

    def test_r8_protection_unknown_no_new_risk_reduce_survives(self):
        out = _eval(
            **_base(
                account_truth=PROT_UNKNOWN,
                thesis_invalidated=True,
            )
        )
        self.assertIn("PROTECTION_TRUTH_UNKNOWN", out["blockers"])
        self.assertFalse(out["open_new_risk"])
        self.assertEqual(out["btc_overlay_action"], "CLOSE_OVERLAY")

    def test_r9_not_connected_never_no_event_rewrite(self):
        out = _eval(**_base(event_input=EVENT_NC_SCHEMA))
        self.assertEqual(out["event_increment_request"], "NONE")
        reasons = " ".join(out["reasons"])
        self.assertIn("NOT_CONNECTED", reasons)

    def test_r10_deterministic(self):
        inp = _base(event_input=EVENT_ELIG_SCHEMA)
        a = evaluate_decision(build_normalized_decision_input(**inp))
        b = evaluate_decision(build_normalized_decision_input(**inp))
        self.assertEqual(_dump(a), _dump(b))

    def test_r11_policy_hash_changes_decision_key(self):
        inp = _base()
        pol_a = default_decision_policy()
        pol_b = default_decision_policy()
        pol_b["policy_hash"] = "different-policy-hash"
        out_a = evaluate_decision(build_normalized_decision_input(**inp), pol_a)
        out_b = evaluate_decision(build_normalized_decision_input(**inp), pol_b)
        self.assertNotEqual(out_a["decision_key"], out_b["decision_key"])

    def test_r13_idempotent_same_key_no_repeat_delta(self):
        inp = _base(
            value_input=VALUE_CONFIRMED_SCHEMA,
            trend_eth={**TREND_ETH_L3, "trend_level": "L4/5"},
            current_state=CURRENT_80_10,
        )
        first = evaluate_decision(build_normalized_decision_input(**inp))
        inp["previous_decision"] = {
            "decision_key": first["decision_key"],
            "based_on_account_version": "a1",
        }
        second = evaluate_decision(build_normalized_decision_input(**inp))
        self.assertTrue(second["idempotent"])
        self.assertEqual(second["delta_proposal"]["status"], "IDEMPOTENT")
        self.assertEqual(second["delta_proposal"]["eth"], 0.0)


class PolicyTests(unittest.TestCase):
    def test_percentages_from_policy_not_hardcoded_magic(self):
        pol = default_decision_policy()
        out = _eval(
            **_base(
                value_input=VALUE_CONFIRMED_SCHEMA,
                trend_eth={**TREND_ETH_L3, "trend_level": "L4/5"},
                current_state=CURRENT_80_10,
            ),
        )
        band = pol["eth_confirmed_band"]
        self.assertAlmostEqual(out["target_state"]["eth"], band["eth"], places=4)
        self.assertEqual(pol["parameter_status"], "PROVISIONAL_E3_PARAM")


if __name__ == "__main__":
    unittest.main()
