"""P3-G0 Entry Gate Audit — G1–G14 acceptance authority."""
from __future__ import annotations

import ast
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from aurora.decision_brain_entry_gate import (  # noqa: E402
    CONTRACT_HASH_A,
    CONTRACT_HASH_B,
    CONTRACT_HASH_C,
    FORBIDDEN_OUTPUT_EXTENDED,
    GATE_KIND,
    T1_T10_FIXTURE_HASH,
    audit_unknown_cross_engine,
    build_brain_decision_key,
    compose_harness_input,
    evaluate_portfolio_decision_candidate,
    get_input_contract_registry,
    normalize_event_decision_input,
    normalize_trend_decision_input,
    normalize_value_decision_input,
    run_entry_gate_audit,
    scan_forbidden_imports,
    verify_t1_t10_fixture_integrity,
)
from aurora.decision_brain_harness import (  # noqa: E402
    evaluate_contract,
    evaluate_pre_submit_revalidation,
    evaluate_protection_authority,
)
from aurora.event_observatory import build_event_observatory_snapshot
from tests.fixtures.decision_brain_entry_gate_g0_cases import (  # noqa: E402
    g3_vote_violation_inputs,
    g5_not_connected,
    g6_account_unknown,
    g7_position_unknown,
    g8_close_survives,
    g9_cluster,
    g10_incremental,
)
from tests.fixtures.decision_brain_v1_1_cases import (  # noqa: E402
    ALL_T_CASES,
    T10_PROTECTION_ACK_ONLY,
    T2_BTC_L4_ETH_L4,
    T3_TREND_EVENT_SAME_DIR,
    T5_ACCOUNT_UNKNOWN,
    T6_CLOSE_WHILE_OPEN_BLOCKED,
    T8_FRESH_EVIDENCE,
    T9_PLAN_SNAPSHOT,
    T9_SUBMIT_SNAPSHOT_DRIFT,
)
from tests.fixtures.event_observatory_c3_cases import SCENARIO_B  # noqa: E402


FIXTURE_PATH = os.path.join(ROOT, "tests", "fixtures", "decision_brain_v1_1_cases.py")
GATE_PATH = os.path.join(ROOT, "aurora", "decision_brain_entry_gate.py")
HARNESS_PATH = os.path.join(ROOT, "aurora", "decision_brain_harness.py")


def _dump(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


class G1Tests(unittest.TestCase):
    """G1 — T1–T10 acceptance authority unchanged."""

    def test_t1_t10_all_pass(self):
        for case in ALL_T_CASES:
            out = evaluate_contract(case)
            self.assertIn("target_state", out)
            self.assertFalse(out["submit_allowed"])
        out_fresh = evaluate_contract(T8_FRESH_EVIDENCE)
        self.assertEqual(out_fresh["rearm_state"], "RE_ARM")

    def test_t9_t10_guards(self):
        drift = evaluate_pre_submit_revalidation(T9_PLAN_SNAPSHOT, T9_SUBMIT_SNAPSHOT_DRIFT)
        self.assertEqual(drift["pre_submit_revalidation"], "PLAN_EXPIRED")
        prot = evaluate_protection_authority(T10_PROTECTION_ACK_ONLY)
        self.assertFalse(prot["is_active_stop"])


class G2G3G4SchemaTests(unittest.TestCase):
    def test_g2_p2_a_schema_stable(self):
        reg = get_input_contract_registry()
        self.assertEqual(reg["P2-A"]["contract_hash"], CONTRACT_HASH_A)
        trend = normalize_trend_decision_input({
            "btc": {
                "trend_direction": "BULL",
                "trend_level": "L4/5",
                "action_eligibility": "LONG_ELIGIBLE",
                "freshness": "ok",
                "blockers": [],
            },
        })
        for f in reg["P2-A"]["required_fields"]:
            self.assertIn(f, trend)

    def test_g3_p2_b_schema_stable(self):
        reg = get_input_contract_registry()
        self.assertEqual(reg["P2-B"]["contract_hash"], CONTRACT_HASH_B)

    def test_g4_p2_c_schema_stable(self):
        reg = get_input_contract_registry()
        self.assertEqual(reg["P2-C"]["contract_hash"], CONTRACT_HASH_C)
        snap = build_event_observatory_snapshot(
            official_sources_connected=False,
        )
        norm = normalize_event_decision_input(snap)
        for f in reg["P2-C"]["required_fields"]:
            self.assertIn(f, norm)

    def test_g3_unknown_not_outvoted(self):
        v = audit_unknown_cross_engine(**g3_vote_violation_inputs())
        self.assertTrue(v)
        inp = dict(g3_vote_violation_inputs())
        inp["trend_eth"] = inp["trend_btc"]
        inp["case_id"] = "G3-VOTE"
        out = evaluate_portfolio_decision_candidate(inp)
        self.assertTrue(out["block_new_risk"])
        self.assertTrue(any("TREND_TRUTH_UNKNOWN" in b for b in out["blockers"]))


class G5G14ScenarioTests(unittest.TestCase):
    def test_g5_event_not_connected_stable_no_boost(self):
        out = evaluate_portfolio_decision_candidate(g5_not_connected())
        self.assertEqual(out["event_increment_budget"], 0.0)
        self.assertFalse(out["submit_allowed"])
        self.assertNotIn("NO_EVENT_OBSERVED", json.dumps(out))

    def test_g6_account_unknown_delta_unavailable(self):
        out = evaluate_portfolio_decision_candidate(g6_account_unknown())
        self.assertEqual(out["delta_status"], "UNAVAILABLE")
        self.assertIn("ACCOUNT_TRUTH_UNKNOWN", out["blockers"])
        self.assertTrue(out["block_new_risk"])

    def test_g7_position_unknown_blocks_new_risk(self):
        out = evaluate_portfolio_decision_candidate(g7_position_unknown())
        self.assertTrue(out["block_new_risk"])

    def test_g8_close_survives_open_block(self):
        out = evaluate_portfolio_decision_candidate({"harness_input": g8_close_survives()})
        self.assertTrue(out["close_allowed"])
        self.assertEqual(out["overlay_action"], "CLOSE_OVERLAY")

    def test_g9_crypto_beta_cluster(self):
        out = evaluate_portfolio_decision_candidate({"harness_input": g9_cluster()})
        c = out["crypto_beta_cluster"]
        self.assertLessEqual(c["total"], c["cluster_cap"] + 1e-9)
        self.assertLess(c["btc"], c["per_trade_cap"])
        self.assertLess(c["eth"], c["per_trade_cap"])

    def test_g10_event_incremental_not_double_count(self):
        out = evaluate_portfolio_decision_candidate({"harness_input": g10_incremental()})
        base = out["cluster_overlay_risk"]["total"]
        inc = out["event_increment_budget"]
        self.assertGreater(inc, 0)
        self.assertLessEqual(base + inc, out["cluster_overlay_risk"]["cluster_cap"] + inc + 1e-9)

    def test_g11_idempotent_decision_key(self):
        key = build_brain_decision_key(
            trend_epoch="e1", value_epoch="v1",
            event_id="evt1", event_version=1,
            account_version="a1", position_version="p1",
        )
        a = evaluate_portfolio_decision_candidate({
            "harness_input": T2_BTC_L4_ETH_L4,
            "brain_decision_key": key,
        })
        b = evaluate_portfolio_decision_candidate({
            "harness_input": T2_BTC_L4_ETH_L4,
            "brain_decision_key": key,
            "previous_decision": {"brain_decision_key": key},
        })
        self.assertEqual(_dump(a["target_state"]), _dump(b["target_state"]))
        self.assertTrue(b["idempotent"])

    def test_g12_forbidden_imports(self):
        for path in (GATE_PATH, HARNESS_PATH):
            hits = scan_forbidden_imports(path)
            self.assertEqual(hits, [], msg=f"{path} imports {hits}")

    def test_g13_no_execution_output_keys(self):
        cases = [
            g5_not_connected(),
            {"harness_input": T3_TREND_EVENT_SAME_DIR},
            {"harness_input": T5_ACCOUNT_UNKNOWN},
            {"harness_input": T6_CLOSE_WHILE_OPEN_BLOCKED},
        ]
        for case in cases:
            out = evaluate_portfolio_decision_candidate(case)
            blob = json.dumps(out)
            for key in FORBIDDEN_OUTPUT_EXTENDED:
                self.assertNotIn(f'"{key}"', blob)

    def test_g14_fixture_hash_unchanged(self):
        ok, digest = verify_t1_t10_fixture_integrity(FIXTURE_PATH)
        self.assertTrue(ok, f"fixture hash drift: {digest} != {T1_T10_FIXTURE_HASH}")


class G0RegistryTests(unittest.TestCase):
    def test_run_entry_gate_audit_pass(self):
        audit = run_entry_gate_audit()
        self.assertEqual(audit["gate_kind"], GATE_KIND)
        self.assertEqual(audit["status"], "PASS")
        self.assertTrue(audit["t1_t10_fixture_hash_ok"])
        self.assertFalse(audit["submit_allowed"])

    def test_observatory_event_not_connected_composes_safely(self):
        obs_event = build_event_observatory_snapshot(official_sources_connected=False)
        event_in = normalize_event_decision_input(obs_event)
        self.assertEqual(event_in["official_source_ingestion"], "NOT_CONNECTED")
        harness = compose_harness_input(
            trend_btc=normalize_trend_decision_input({"btc": {"trend_direction": "BULL", "trend_level": "L4/5", "action_eligibility": "LONG_ELIGIBLE", "freshness": "ok", "blockers": []}}),
            trend_eth=normalize_trend_decision_input({"eth": {"trend_direction": "BULL", "trend_level": "L3/5", "action_eligibility": "LONG_ELIGIBLE", "freshness": "ok", "blockers": []}}, asset="eth"),
            value_input=normalize_value_decision_input({"value_zone": "FAIR", "allocation": {"allocation_signal": "HOLD_BTC", "state": "BTC_DEFAULT"}, "blockers": []}),
            event_input=event_in,
            case_id="OBS-NC",
        )
        out = evaluate_portfolio_decision_candidate({"harness_input": harness})
        self.assertEqual(out["event_increment_budget"], 0.0)

    def test_connected_fixture_event_projection(self):
        snap = build_event_observatory_snapshot(**{
            k: v for k, v in SCENARIO_B.items() if k != "case_id"
        })
        event_in = normalize_event_decision_input(snap)
        self.assertEqual(event_in["boost_eligibility"], "EVENT_BOOST_ELIGIBLE")


class NoPortfolioBrainV2Tests(unittest.TestCase):
    def test_entry_gate_never_imports_v2(self):
        path = GATE_PATH
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        modules = [
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        ]
        self.assertNotIn("aurora.portfolio_brain_v2", modules)


if __name__ == "__main__":
    unittest.main()
