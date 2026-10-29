"""P3-R3.1 Risk Adjudicator — R31-1～R31-21 runtime acceptance.

Red until aurora/risk_adjudicator.py exists. These tests are the runtime
contract. They do not replace tests/test_risk_contract_r3.py.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import unittest
from decimal import Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from aurora.risk_contract_harness import evaluate_risk  # noqa: E402

E2_SHA256 = "27f36b3de9b01f89e8dd5d360d7f219345c00bf086652af2a50241ff8440ef84"
E1_SHA256 = "c0f7a700da1e483d6af3621abf1b057eea8177275428dafd7155e85ab68bcdf3"
BASELINE_COMMIT = "745e4e0a7737ba2945bc50243be449264759e1b3"

EVAL = "2026-10-28T01:00:00Z"
ASOF = "2026-10-28T00:30:00Z"

FORBIDDEN_OUTPUT = (
    "order_id",
    "client_order_id",
    "exchange_qty",
    "submit",
    "execute",
    "close_position",
    "place_order",
)
FORBIDDEN_IMPORTS = (
    "portfolio_brain_v2",
    "risk_gate",
    "risk_kernel",
    "trading_cycle",
    "ops_t3_extended",
    "ops_controlled_requal",
    "production_main",
    "execution_engine",
    "execution_engine_v2",
    "execution_truth",
    "binance_exchange",
    "armed_runtime",
)
OLD_CHAIN = (
    "aurora/trading_cycle.py",
    "aurora/production_main.py",
    "aurora/ops_t3_extended.py",
    "aurora/ops_controlled_requal.py",
    "aurora/portfolio_brain_v2.py",
)


def _dec_hook(obj):
    if isinstance(obj, list):
        return [_dec_hook(x) for x in obj]
    if isinstance(obj, dict):
        if set(obj.keys()) == {"__decimal__"}:
            return Decimal(obj["__decimal__"])
        return {k: _dec_hook(v) for k, v in obj.items()}
    return obj


def _enc(obj):
    if isinstance(obj, Decimal):
        return {"__decimal__": format(obj, "f")}
    if isinstance(obj, dict):
        return {k: _enc(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_enc(v) for v in obj]
    return obj


def _policy(**overrides):
    base = {
        "policy_version": "p3-r31-v1",
        "source": "SYNTHETIC",
        "parameter_status": "PROVISIONAL_E3_PARAM",
        "per_trade_loss_budget": Decimal("6"),
        "cluster_loss_budget": Decimal("6"),
        "overlay_pool_loss_budget": Decimal("6"),
        "event_increment_budget": Decimal("3"),
        "managed_gross_exposure_max": Decimal("100"),
        "funding_cost_budget": Decimal("0.002"),
        "drawdown_budget": Decimal("0.15"),
        "stress_policy": {"enabled": True, "haircut": Decimal("0.85")},
        "sizing_policy": {
            "min_unit_loss": Decimal("0.000000001"),
            "qty_step": Decimal("0.001"),
        },
        "sla_rule_id": "sla-v1",
        "sla_decision_sec": Decimal("86400"),
        "sla_account_sec": Decimal("86400"),
        "sla_market_sec": Decimal("86400"),
        "skew_limit_sec": Decimal("3600"),
    }
    base.update(overrides)
    if "policy_hash" not in base:
        from aurora.risk_adjudicator import policy_content_hash
        base["policy_hash"] = policy_content_hash(base)
    return base


def _decision(**overrides):
    base = {
        "decision_key": "dec-v1",
        "source": "SYNTHETIC",
        "as_of": ASOF,
        "current_state": {
            "status": "KNOWN",
            "btc": Decimal("80"),
            "eth": Decimal("10"),
            "usdt": Decimal("10"),
            "btc_overlay": Decimal("0"),
            "eth_overlay": Decimal("0"),
            "event_increment": Decimal("0"),
        },
        "target_state": {
            "status": "KNOWN",
            "btc": Decimal("80"),
            "eth": Decimal("10"),
            "usdt": Decimal("10"),
            "btc_overlay": Decimal("1"),
            "eth_overlay": Decimal("0"),
            "event_increment": Decimal("0"),
        },
        "delta_proposal": {
            "status": "AVAILABLE",
            "btc_overlay": Decimal("1"),
            "eth_overlay": Decimal("0"),
            "event_increment": Decimal("0"),
        },
        "crypto_beta_cluster": {
            "btc_request": Decimal("1"),
            "eth_request": Decimal("0"),
            "total_request": Decimal("1"),
        },
        "event_increment_request": "NONE",
        "submit_allowed": False,
        "btc_overlay_action": "INCREASE_CANDIDATE",
    }
    base.update(overrides)
    return base


def _account(**overrides):
    base = {
        "source": "SYNTHETIC",
        "status": "KNOWN",
        "account_version": "acc-v1",
        "position_version": "pos-v1",
        "protection_version": "prot-v1",
        "as_of": ASOF,
        "btc_nav": Decimal("1.25"),
        "equity": Decimal("100000"),
        "drawdown": Decimal("0.05"),
        "positions": {
            "status": "KNOWN",
            "btc_overlay": Decimal("0.01"),
        },
        "protection_state": "ACTIVE_CONFIRMED",
        "proposed_protection_state": "ACTIVE_CONFIRMED",
        "kill": "CLEAR",
        "incident": "CLEAR",
    }
    base.update(overrides)
    return base


def _market(**overrides):
    base = {
        "source": "SYNTHETIC",
        "quote_version": "q-v1",
        "freshness": "ok",
        "as_of": ASOF,
        "btc_funding": Decimal("0.0001"),
        "spread": Decimal("0.0002"),
    }
    base.update(overrides)
    return base


def _defensive_decision(**overrides):
    base = _decision(
        btc_overlay_action="CLOSE_OVERLAY",
        spot_action="REDUCE_OR_CLOSE",
        close_allowed=True,
        reduce_allowed=True,
        thesis_invalidated=True,
        crypto_beta_cluster={
            "btc_request": Decimal("0"),
            "eth_request": Decimal("0"),
            "total_request": Decimal("0"),
        },
        event_increment_request="NONE",
        target_state={
            "status": "KNOWN",
            "btc_overlay": Decimal("0"),
            "eth_overlay": Decimal("0"),
            "event_increment": Decimal("0"),
        },
        delta_proposal={
            "status": "AVAILABLE",
            "btc_overlay": Decimal("0"),
            "eth_overlay": Decimal("0"),
            "event_increment": Decimal("0"),
        },
    )
    base.update(overrides)
    return base


def _flat_positions():
    return {"status": "KNOWN", "btc_overlay": Decimal("0"), "eth_overlay": Decimal("0")}


def _sha_file(rel):
    data = open(os.path.join(ROOT, rel), "rb").read()
    return hashlib.sha256(data).hexdigest()


def _walk_keys(obj, found):
    if isinstance(obj, dict):
        for key, val in obj.items():
            found.add(key)
            _walk_keys(val, found)
    elif isinstance(obj, list):
        for val in obj:
            _walk_keys(val, found)


def _num(val):
    return Decimal(str(val))


class R31AcceptanceTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.log = os.path.join(self.tmp, "plan.sqlite")

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, **kw):
        from aurora.risk_adjudicator import adjudicate_runtime
        return adjudicate_runtime(
            kw.get("decision") if "decision" in kw else _decision(),
            kw.get("account") if "account" in kw else _account(),
            kw.get("market") if "market" in kw else _market(),
            kw.get("policy") if "policy" in kw else _policy(),
            evaluation_at=kw.get("evaluation_at", EVAL),
            log_path=kw.get("log_path", self.log),
            risk_evaluator=kw.get("risk_evaluator"),
            before_commit=kw.get("before_commit"),
            connection=kw.get("connection"),
        )

    def _assert_no_order(self, record):
        self.assertFalse(record["submit_allowed"])
        self.assertEqual(record["order_intent"], "ABSENT")
        self.assertEqual(record["execution_eligibility"], "DENIED")
        found = set()
        _walk_keys(record, found)
        for key in FORBIDDEN_OUTPUT:
            self.assertNotIn(key, found)
        self.assertNotIn("idempotent", found)
        self.assertNotIn("wrote_now", found)
        self.assertNotIn("record_present", found)

    def _bindings(self):
        from aurora.risk_adjudicator import read_bindings
        return read_bindings(self.log)

    def _records(self, path=None):
        from aurora.risk_adjudicator import read_records
        return read_records(path or self.log)

    def test_r31_1_in_process_record_has_no_order(self):
        out = self._run()
        self.assertTrue(out["receipt"]["wrote_now"])
        self.assertTrue(out["receipt"]["record_present"])
        self.assertFalse(out["receipt"]["idempotent"])
        self._assert_no_order(out["record"])
        self.assertEqual(out["record"]["account_authority"], "NOT_ESTABLISHED")
        self.assertEqual(len(self._records()), 1)
        self.assertNotIn("kernel_ledger.db", open(
            os.path.join(ROOT, "aurora", "risk_adjudicator.py"), encoding="utf-8"
        ).read())

    def test_r31_2_same_input_record_bytes_receipt_differs(self):
        first = self._run()
        second = self._run()
        self.assertEqual(first["record_canonical"], second["record_canonical"])
        self.assertTrue(first["receipt"]["wrote_now"])
        self.assertFalse(first["receipt"]["idempotent"])
        self.assertTrue(first["receipt"]["record_present"])
        self.assertFalse(second["receipt"]["wrote_now"])
        self.assertTrue(second["receipt"]["idempotent"])
        self.assertTrue(second["receipt"]["record_present"])
        self.assertEqual(len(self._records()), 1)
        self.assertEqual(self._records()[0]["record_canonical"], first["record_canonical"])

    def test_r31_3_request_10_policy_6_reduced(self):
        decision = _decision(
            crypto_beta_cluster={
                "btc_request": Decimal("10"),
                "eth_request": Decimal("0"),
                "total_request": Decimal("10"),
            },
            target_state={
                "status": "KNOWN",
                "btc_overlay": Decimal("10"),
                "eth_overlay": Decimal("0"),
                "event_increment": Decimal("0"),
            },
        )
        out = self._run(decision=decision)
        self.assertEqual(out["record"]["risk_state"], "REDUCED")
        allowed = _num(out["record"]["new_risk"]["allowed"])
        requested = _num(out["record"]["new_risk"]["requested"])
        self.assertEqual(requested, Decimal("10"))
        self.assertEqual(allowed, Decimal("6"))
        self.assertLessEqual(allowed, Decimal("6"))
        self.assertTrue(out["record"]["new_risk_allowed"])

    def test_r31_4_inflated_output_is_not_persisted(self):
        def inflate(candidate, truth, policy=None, **kwargs):
            out = evaluate_risk(candidate, truth, policy)
            out["crypto_beta_cluster"]["allowed"]["btc"] = 999
            out["crypto_beta_cluster"]["allowed"]["total"] = 999
            out["loss_budget"]["allowed"] = 999
            out["_gross_exposure_allowed"] = 999
            return out

        out = self._run(risk_evaluator=inflate)
        self.assertEqual(out["record"]["risk_state"], "BLOCK_NEW_RISK")
        self.assertIn("RISK_MONOTONICITY_VIOLATION", out["record"]["blockers"])
        self.assertFalse(out["record"]["new_risk_allowed"])
        self.assertNotEqual(out["record"]["risk_state"], "PASS")
        self.assertFalse(out["receipt"]["wrote_now"])
        self.assertFalse(out["receipt"]["record_present"])
        self.assertEqual(self._records(), [])

    def test_r31_5_null_nav_blocks_without_zero_fill(self):
        out = self._run(account=_account(btc_nav=None))
        self.assertEqual(out["record"]["risk_state"], "BLOCK_NEW_RISK")
        self.assertIn("BTC_NAV_UNKNOWN", out["record"]["blockers"])
        self.assertFalse(out["record"]["new_risk_allowed"])
        bodies = [row["canonical_body"] for row in self._bindings() if row["object_name"] == "account"]
        self.assertEqual(len(bodies), 1)
        self.assertIn('"btc_nav":null', bodies[0])
        self.assertNotIn('"btc_nav":0', bodies[0])

    def test_r31_6_stale_account_or_quote_blocks_new_risk(self):
        stale_account = self._run(
            account=_account(status="STALE"),
            log_path=os.path.join(self.tmp, "stale-account.sqlite"),
        )
        self.assertEqual(stale_account["record"]["risk_state"], "BLOCK_NEW_RISK")
        self.assertFalse(stale_account["record"]["new_risk_allowed"])
        self.assertIn("ACCOUNT_STALE", stale_account["record"]["blockers"])

        unknown_quote = self._run(
            market=_market(freshness="unknown", quote_version="q-unknown"),
            log_path=os.path.join(self.tmp, "stale-quote.sqlite"),
        )
        self.assertEqual(unknown_quote["record"]["risk_state"], "BLOCK_NEW_RISK")
        self.assertFalse(unknown_quote["record"]["new_risk_allowed"])
        self.assertTrue(
            "MARKET_UNKNOWN" in unknown_quote["record"]["blockers"]
            or "MARKET_STALE" in unknown_quote["record"]["blockers"]
        )

    def test_r31_7_unknown_position_defensive_quantity_unavailable(self):
        out = self._run(
            decision=_defensive_decision(),
            account=_account(positions=None),
        )
        self.assertTrue(out["record"]["defensive_intent_preserved"])
        self.assertEqual(out["record"]["defensive_quantity"], "UNAVAILABLE")
        self.assertFalse(out["record"]["new_risk_allowed"])
        self.assertEqual(out["record"]["execution_eligibility"], "DENIED")
        self.assertNotEqual(out["record"]["existing_position_protection"], "NOT_APPLICABLE")

    def _protection_trio(self, run):
        flat = run(
            decision=_decision(decision_key="dec-flat"),
            account=_account(
                account_version="acc-flat",
                positions=_flat_positions(),
                protection_state="ACTIVE_CONFIRMED",
                proposed_protection_state="PROPOSED",
            ),
        )
        self.assertEqual(flat["record"]["existing_position_protection"], "NOT_APPLICABLE")
        self.assertEqual(flat["record"]["risk_state"], "BLOCK_NEW_RISK")
        self.assertIn("PROTECTION_UNMET", flat["record"]["blockers"])
        self.assertFalse(flat["record"]["new_risk_allowed"])
        self.assertNotEqual(flat["record"]["risk_state"], "PASS")

        held = run(
            decision=_decision(decision_key="dec-held"),
            account=_account(
                account_version="acc-held",
                positions={"status": "KNOWN", "btc_overlay": Decimal("0.5")},
                protection_state="PENDING",
                proposed_protection_state="ACTIVE_CONFIRMED",
            ),
        )
        self.assertNotEqual(held["record"]["existing_position_protection"], "NOT_APPLICABLE")
        self.assertEqual(held["record"]["existing_position_protection"], "PENDING")
        self.assertIn("EXISTING_POSITION_UNPROTECTED", held["record"]["blockers"])
        self.assertFalse(held["record"]["new_risk_allowed"])
        self.assertEqual(held["record"]["risk_state"], "BLOCK_NEW_RISK")

        pure = run(
            decision=_defensive_decision(decision_key="dec-def"),
            account=_account(account_version="acc-def"),
        )
        self.assertTrue(pure["record"]["defensive_intent_preserved"])
        self.assertEqual(pure["record"]["risk_state"], "DEFENSIVE_ONLY")
        self.assertEqual(pure["record"]["execution_eligibility"], "DENIED")
        self.assertFalse(pure["record"]["new_risk_allowed"])
        self.assertNotEqual(pure["record"]["risk_state"], "PASS")

    def test_r31_8_protection_cases_stay_separate(self):
        self._protection_trio(self._run)

    def test_r31_9_eth_and_event_execution_stay_denied(self):
        decision = _decision(
            crypto_beta_cluster={
                "btc_request": Decimal("1"),
                "eth_request": Decimal("1"),
                "total_request": Decimal("2"),
            },
            event_increment_request="ELIGIBLE",
            target_state={
                "status": "KNOWN",
                "btc_overlay": Decimal("1"),
                "eth_overlay": Decimal("1"),
                "event_increment": Decimal("1"),
            },
            current_state={
                "status": "KNOWN",
                "btc_overlay": Decimal("0"),
                "eth_overlay": Decimal("0"),
                "event_increment": Decimal("0"),
            },
        )
        out = self._run(decision=decision)
        fence = out["record"]["identity_fence"]
        self.assertEqual(fence["eth_overlay_execution"], "DENIED")
        self.assertEqual(fence["event_increment_execution"], "DENIED")
        self.assertEqual(out["record"]["execution_eligibility"], "DENIED")
        requested = out["record"]["requested_cluster"]
        self.assertEqual(_num(requested["eth"]), Decimal("1"))
        self.assertEqual(_num(out["record"]["requested_event_increment"]), Decimal("1"))

    def test_r31_10_kill_blocks_new_risk_and_probes_stay_zero(self):
        counts = self._install_probes()
        try:
            out = self._run(
                decision=_defensive_decision(
                    crypto_beta_cluster={
                        "btc_request": Decimal("1"),
                        "eth_request": Decimal("0"),
                        "total_request": Decimal("1"),
                    },
                    btc_overlay_action="INCREASE_CANDIDATE",
                    close_allowed=True,
                    reduce_allowed=True,
                    thesis_invalidated=True,
                ),
                account=_account(kill="ACTIVE"),
            )
        finally:
            self._restore_probes()
        self.assertFalse(out["record"]["new_risk_allowed"])
        self.assertTrue(out["record"]["defensive_intent_preserved"])
        self.assertIn(out["record"]["risk_state"], ("BLOCK_NEW_RISK", "DEFENSIVE_ONLY"))
        self.assertEqual(out["record"]["execution_eligibility"], "DENIED")
        self.assertEqual(counts, {k: 0 for k in counts})

    def test_r31_11_cross_process_replay_bytes(self):
        first = self._run()
        child = self._replay_in_subprocess()
        self.assertEqual(child["record_canonical"], first["record_canonical"])
        self.assertTrue(child["receipt"]["idempotent"])
        self.assertFalse(child["receipt"]["wrote_now"])
        self.assertTrue(child["receipt"]["record_present"])
        self.assertEqual(len(self._records()), 1)

    def test_r31_12_mid_write_failure_rolls_back_and_retry_matches(self):
        def boom(_conn):
            raise sqlite3.OperationalError("injected write failure")

        failed = self._run(before_commit=boom)
        self.assertFalse(failed["receipt"]["wrote_now"])
        self.assertFalse(failed["receipt"]["record_present"])
        self.assertNotEqual(failed["record"]["risk_state"], "PASS")
        self.assertEqual(self._records(), [])

        clean_dir = os.path.join(self.tmp, "clean")
        os.makedirs(clean_dir)
        clean = self._run(log_path=os.path.join(clean_dir, "plan.sqlite"))
        retried = self._run()
        self.assertEqual(retried["record_canonical"], clean["record_canonical"])
        self.assertTrue(retried["receipt"]["wrote_now"])
        self.assertEqual(len(self._records()), 1)

        side = os.path.join(self.tmp, "caller.sqlite")
        conn = sqlite3.connect(side, timeout=10, isolation_level=None, check_same_thread=False)
        try:
            from aurora.risk_adjudicator import CallerTransactionOpen
            conn.execute("CREATE TABLE caller_scratch (id INTEGER)")
            conn.execute("BEGIN")
            conn.execute("INSERT INTO caller_scratch (id) VALUES (1)")
            with self.assertRaises(CallerTransactionOpen):
                self._run(connection=conn, log_path=side)
            conn.rollback()
            left = conn.execute("SELECT COUNT(*) FROM caller_scratch").fetchone()[0]
            self.assertEqual(left, 0)
        finally:
            conn.close()

    def test_r31_13_runtime_probes_stay_zero(self):
        counts = self._install_probes()
        try:
            self._run()
        finally:
            self._restore_probes()
        self.assertEqual(counts, {k: 0 for k in counts})

    def test_r31_14_static_import_scan(self):
        path = os.path.join(ROOT, "aurora", "risk_adjudicator.py")
        source = open(path, encoding="utf-8").read()
        tree = ast.parse(source)
        modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
        for mod in modules:
            low = mod.lower()
            for banned in FORBIDDEN_IMPORTS:
                self.assertNotIn(banned, low)
        self.assertNotIn("executescript", source)
        self.assertNotIn("UPDATE ", source.upper())
        self.assertNotIn("datetime.now", source)
        self.assertNotIn("time.time", source)
        for rel in OLD_CHAIN:
            text = open(os.path.join(ROOT, rel), encoding="utf-8").read()
            self.assertNotIn("adjudicate_runtime", text)
            self.assertNotIn("risk_adjudicator", text)

    def test_r31_15_e2_e1_hashes_match_baseline(self):
        self.assertEqual(_sha_file("aurora/strategy_v2.py"), E2_SHA256)
        self.assertEqual(_sha_file("aurora/risk_semantics.py"), E1_SHA256)
        baseline = open(os.path.join(ROOT, "evidence", "p3_r3_1", "BASELINE.md"), encoding="utf-8").read()
        self.assertIn(E2_SHA256, baseline)
        self.assertIn(E1_SHA256, baseline)
        self.assertIn(BASELINE_COMMIT, baseline)

    def test_r31_16_declaration_conflict_and_legal_new_version(self):
        first = self._run()
        first_bytes = first["record_canonical"]
        account_bindings = [row for row in self._bindings() if row["object_name"] == "account"]
        self.assertEqual(len(account_bindings), 1)
        bound_hash = account_bindings[0]["content_hash"]
        bound_body = account_bindings[0]["canonical_body"]

        conflict = self._run(
            account=_account(btc_nav=Decimal("1.26")),
            evaluation_at="2026-10-28T03:00:00Z",
        )
        self.assertIn("INPUT_IDENTITY_CONFLICT", conflict["record"]["blockers"])
        self.assertEqual(conflict["record"]["risk_state"], "BLOCK_NEW_RISK")
        self.assertFalse(conflict["receipt"]["wrote_now"])
        self.assertFalse(conflict["receipt"]["idempotent"])
        self.assertTrue(conflict["receipt"]["record_present"])
        self.assertNotEqual(conflict["record"]["risk_state"], "PASS")
        again = [row for row in self._bindings() if row["object_name"] == "account"]
        self.assertEqual(len(again), 1)
        self.assertEqual(again[0]["content_hash"], bound_hash)
        self.assertEqual(again[0]["canonical_body"], bound_body)
        self.assertNotIn("1.26", bound_body)
        self.assertEqual(self._records()[0]["record_canonical"], first_bytes)

        legal = self._run(
            account=_account(account_version="acc-v2", btc_nav=Decimal("1.26")),
            evaluation_at="2026-10-28T04:00:00Z",
        )
        self.assertTrue(legal["receipt"]["wrote_now"])
        self.assertNotIn("INPUT_IDENTITY_CONFLICT", legal["record"]["blockers"])
        self.assertNotEqual(legal["record_canonical"], first_bytes)
        self.assertEqual(self._records()[0]["record_canonical"], first_bytes)
        self.assertEqual(len([row for row in self._bindings() if row["object_name"] == "account"]), 2)

        shifted = self._run(evaluation_at="2026-10-28T05:00:00Z")
        self.assertTrue(shifted["receipt"]["wrote_now"])
        self.assertNotIn("INPUT_IDENTITY_CONFLICT", shifted["record"]["blockers"])
        self.assertEqual(self._records()[0]["record_canonical"], first_bytes)

        forged_log = os.path.join(self.tmp, "forged.sqlite")
        forged = self._run(
            policy=_policy(policy_hash="forged-not-the-body"),
            log_path=forged_log,
        )
        self.assertIn("INPUT_IDENTITY_CONFLICT", forged["record"]["blockers"])
        self.assertFalse(forged["receipt"]["wrote_now"])
        self.assertFalse(forged["receipt"]["record_present"])
        self.assertEqual(self._records(forged_log), [])

    def test_r31_17_time_rules_ignore_wall_clock(self):
        sla = dict(
            sla_decision_sec=Decimal("1800"),
            sla_account_sec=Decimal("1800"),
            sla_market_sec=Decimal("1800"),
            skew_limit_sec=Decimal("3600"),
        )
        on_boundary = self._run(
            policy=_policy(**sla),
            log_path=os.path.join(self.tmp, "boundary.sqlite"),
        )
        self.assertNotIn("SLA_EXCEEDED", on_boundary["record"]["blockers"])
        self.assertNotIn("FUTURE_TIMESTAMP", on_boundary["record"]["blockers"])
        self.assertIn(on_boundary["record"]["risk_state"], ("PASS", "REDUCED"))

        late_decision = _decision(as_of="2026-10-28T00:29:59Z", decision_key="dec-late")
        late_account = _account(as_of="2026-10-28T00:29:59Z", account_version="acc-late")
        late_market = _market(as_of="2026-10-28T00:29:59Z", quote_version="q-late")
        over = self._run(
            decision=late_decision,
            account=late_account,
            market=late_market,
            policy=_policy(**sla),
        )
        self.assertIn("SLA_EXCEEDED", over["record"]["blockers"])
        self.assertEqual(over["record"]["risk_state"], "BLOCK_NEW_RISK")
        self.assertFalse(over["record"]["new_risk_allowed"])

        future = self._run(
            decision=_decision(as_of="2026-10-28T01:00:01Z", decision_key="dec-future"),
            account=_account(as_of="2026-10-28T01:00:01Z", account_version="acc-future"),
            market=_market(as_of="2026-10-28T01:00:01Z", quote_version="q-future"),
            log_path=os.path.join(self.tmp, "future.sqlite"),
        )
        self.assertIn("FUTURE_TIMESTAMP", future["record"]["blockers"])
        self.assertEqual(future["record"]["risk_state"], "BLOCK_NEW_RISK")

        skew = self._run(
            decision=_decision(as_of="2026-10-28T00:00:00Z", decision_key="dec-skew"),
            account=_account(as_of=EVAL, account_version="acc-skew"),
            market=_market(as_of=EVAL, quote_version="q-skew"),
            policy=_policy(skew_limit_sec=Decimal("3599")),
            evaluation_at=EVAL,
            log_path=os.path.join(self.tmp, "skew.sqlite"),
        )
        self.assertIn("SKEW_EXCEEDED", skew["record"]["blockers"])
        self.assertEqual(skew["record"]["risk_state"], "BLOCK_NEW_RISK")

        historical = self._run(log_path=os.path.join(self.tmp, "clock.sqlite"))
        import aurora.risk_contract_harness as harness
        original_now_iso = harness._now_iso
        harness._now_iso = lambda: "2099-01-01T00:00:00Z"
        try:
            replay = self._run(log_path=os.path.join(self.tmp, "clock.sqlite"))
        finally:
            harness._now_iso = original_now_iso
        self.assertEqual(replay["record_canonical"], historical["record_canonical"])
        self.assertNotIn("2099", replay["record_canonical"])

    def test_r31_18_known_does_not_become_authority(self):
        synthetic = self._run(account=_account(status="KNOWN", source="SYNTHETIC"))
        self.assertEqual(synthetic["record"]["account_authority"], "NOT_ESTABLISHED")
        self.assertEqual(synthetic["record"]["claimed_account_source"], "SYNTHETIC")

        claimed = self._run(
            account=_account(
                status="KNOWN",
                source="AUTHORITATIVE",
                account_version="acc-claimed",
            ),
            decision=_decision(decision_key="dec-claimed"),
            log_path=os.path.join(self.tmp, "claimed.sqlite"),
        )
        self.assertEqual(claimed["record"]["account_authority"], "NOT_ESTABLISHED")
        self.assertEqual(claimed["record"]["claimed_account_source"], "AUTHORITATIVE")
        self._protection_trio(
            lambda **kw: self._run(log_path=os.path.join(self.tmp, "prot18.sqlite"), **kw)
        )

    def test_r31_19_invalidation_appends_and_new_version_may_allow_more(self):
        from aurora.risk_adjudicator import append_invalidation
        tight = self._run(
            decision=_decision(
                crypto_beta_cluster={
                    "btc_request": Decimal("1"),
                    "eth_request": Decimal("0"),
                    "total_request": Decimal("1"),
                }
            ),
            policy=_policy(policy_version="pol-tight", cluster_loss_budget=Decimal("1"),
                           per_trade_loss_budget=Decimal("1"), overlay_pool_loss_budget=Decimal("1")),
        )
        old = tight["record_canonical"]
        append_invalidation(self.log, tight["record"]["risk_plan_key"], EVAL, "superseded-for-test")
        wide = self._run(
            decision=_decision(
                decision_key="dec-v2",
                crypto_beta_cluster={
                    "btc_request": Decimal("4"),
                    "eth_request": Decimal("0"),
                    "total_request": Decimal("4"),
                },
                target_state={
                    "status": "KNOWN",
                    "btc_overlay": Decimal("4"),
                    "eth_overlay": Decimal("0"),
                    "event_increment": Decimal("0"),
                },
            ),
            account=_account(account_version="acc-v2"),
            market=_market(quote_version="q-v2"),
            policy=_policy(
                policy_version="pol-wide",
                cluster_loss_budget=Decimal("8"),
                per_trade_loss_budget=Decimal("8"),
                overlay_pool_loss_budget=Decimal("8"),
            ),
            evaluation_at="2026-10-28T06:00:00Z",
        )
        self.assertEqual(self._records()[0]["record_canonical"], old)
        self.assertGreater(
            _num(wide["record"]["new_risk"]["allowed"]),
            _num(tight["record"]["new_risk"]["allowed"]),
        )
        conn = sqlite3.connect(self.log)
        try:
            events = conn.execute("SELECT COUNT(*) FROM invalidation_event").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(events, 1)

    def test_r31_20_numbers_priority_and_unwritable_log(self):
        nan = self._run(account=_account(btc_nav=float("nan")))
        self.assertIn("NON_FINITE", nan["record"]["blockers"])
        self.assertEqual(nan["record"]["risk_state"], "BLOCK_NEW_RISK")
        self.assertFalse(nan["receipt"]["wrote_now"])
        self.assertFalse(nan["receipt"]["record_present"])
        self.assertNotEqual(nan["record"]["risk_state"], "PASS")

        inf = self._run(
            account=_account(btc_nav=float("inf"), account_version="acc-inf"),
            log_path=os.path.join(self.tmp, "inf.sqlite"),
        )
        self.assertIn("NON_FINITE", inf["record"]["blockers"])
        self.assertFalse(inf["receipt"]["wrote_now"])

        sign = self._run(
            account=_account(btc_nav=Decimal("-0.1"), account_version="acc-sign"),
            log_path=os.path.join(self.tmp, "sign.sqlite"),
        )
        self.assertIn("SIGN_MISMATCH", sign["record"]["blockers"])
        self.assertEqual(sign["record"]["risk_state"], "BLOCK_NEW_RISK")
        self.assertFalse(sign["receipt"]["wrote_now"])

        huge = self._run(
            account=_account(btc_nav=Decimal("1000001"), account_version="acc-huge"),
            log_path=os.path.join(self.tmp, "huge.sqlite"),
        )
        self.assertIn("RANGE_VIOLATION", huge["record"]["blockers"])
        self.assertFalse(huge["receipt"]["wrote_now"])

        unit = self._run(
            account=_account(
                btc_nav={"value": Decimal("1"), "unit": "USDT"},
                account_version="acc-unit",
            ),
            log_path=os.path.join(self.tmp, "unit.sqlite"),
        )
        self.assertIn("UNIT_MISMATCH", unit["record"]["blockers"])
        self.assertFalse(unit["receipt"]["wrote_now"])

        zero = self._run(
            account=_account(btc_nav=Decimal("0"), account_version="acc-zero"),
            log_path=os.path.join(self.tmp, "zero.sqlite"),
        )
        self.assertNotIn("BTC_NAV_UNKNOWN", zero["record"]["blockers"])
        self.assertNotEqual(zero["record"]["risk_state"], "UNKNOWN")
        self.assertIn(zero["record"]["risk_state"], ("PASS", "REDUCED"))
        self.assertTrue(zero["record"]["new_risk_allowed"])

        stacked = self._run(
            account=_account(btc_nav=float("nan"), kill="ACTIVE", account_version="acc-stack"),
            policy=_policy(policy_version="pol-stack", skew_limit_sec=None),
            log_path=os.path.join(self.tmp, "stack.sqlite"),
        )
        self.assertEqual(stacked["record"]["risk_state"], "BLOCK_NEW_RISK")
        self.assertNotEqual(stacked["record"]["risk_state"], "UNKNOWN")
        self.assertNotEqual(stacked["record"]["risk_state"], "PASS")
        for code in ("NON_FINITE", "POLICY_INCOMPLETE", "KILL_ACTIVE"):
            self.assertIn(code, stacked["record"]["blockers"])
        self.assertFalse(stacked["receipt"]["wrote_now"])
        self.assertFalse(stacked["receipt"]["record_present"])

        incomplete = self._run(
            policy=_policy(policy_version="pol-null", cluster_loss_budget=None),
            log_path=os.path.join(self.tmp, "incomplete.sqlite"),
        )
        self.assertEqual(incomplete["record"]["risk_state"], "BLOCK_NEW_RISK")
        self.assertNotEqual(incomplete["record"]["risk_state"], "UNKNOWN")
        self.assertIn("POLICY_INCOMPLETE", incomplete["record"]["blockers"])
        self.assertFalse(incomplete["receipt"]["wrote_now"])

        bad_status = self._run(
            policy=_policy(policy_version="pol-final", parameter_status="FINAL"),
            log_path=os.path.join(self.tmp, "status.sqlite"),
        )
        self.assertEqual(bad_status["record"]["risk_state"], "BLOCK_NEW_RISK")
        self.assertIn("PARAMETER_STATUS", bad_status["record"]["blockers"])
        self.assertNotEqual(bad_status["record"]["risk_state"], "UNKNOWN")

        blocker = os.path.join(self.tmp, "not-a-directory")
        with open(blocker, "w", encoding="utf-8") as fh:
            fh.write("x")
        unwritable = self._run(log_path=os.path.join(blocker, "plan.sqlite"))
        self.assertFalse(unwritable["receipt"]["wrote_now"])
        self.assertFalse(unwritable["receipt"]["record_present"])
        self.assertEqual(unwritable["record"]["risk_state"], "BLOCK_NEW_RISK")
        self.assertNotEqual(unwritable["record"]["risk_state"], "PASS")
        self.assertIn("LOG_UNWRITABLE", unwritable["record"]["blockers"])

    def test_r31_21_process_replay_and_concurrent_bindings(self):
        first = self._run()
        children = [self._replay_in_subprocess(), self._replay_in_subprocess()]
        for child in children:
            self.assertEqual(child["record_canonical"], first["record_canonical"])
            self.assertTrue(child["receipt"]["idempotent"])
            self.assertFalse(child["receipt"]["wrote_now"])
        self.assertEqual(len(self._records()), 1)

        same_log = os.path.join(self.tmp, "same.sqlite")
        from aurora.risk_adjudicator import open_plan_log
        c1 = open_plan_log(same_log)
        c2 = open_plan_log(same_log)
        barrier = threading.Barrier(2)
        outs = []
        errors = []

        def _same(conn):
            try:
                barrier.wait(5)
                outs.append(self._run(connection=conn, log_path=same_log))
            except BaseException as exc:  # noqa: BLE001 — surface the thread failure
                errors.append(exc)

        threads = [threading.Thread(target=_same, args=(c1,)), threading.Thread(target=_same, args=(c2,))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(20)
        c1.close()
        c2.close()
        self.assertEqual(errors, [])
        self.assertEqual(len(outs), 2)
        self.assertEqual(outs[0]["record_canonical"], outs[1]["record_canonical"])
        self.assertEqual(sum(1 for item in outs if item["receipt"]["wrote_now"]), 1)
        self.assertEqual(sum(1 for item in outs if item["receipt"]["idempotent"]), 1)
        self.assertEqual(len(self._records(same_log)), 1)

        diff_log = os.path.join(self.tmp, "diff.sqlite")
        d1 = open_plan_log(diff_log)
        d2 = open_plan_log(diff_log)
        barrier2 = threading.Barrier(2)
        diff_outs = []

        def _diff(conn, nav):
            barrier2.wait(5)
            diff_outs.append((nav, self._run(
                connection=conn,
                log_path=diff_log,
                account=_account(btc_nav=nav),
            )))

        t1 = threading.Thread(target=_diff, args=(d1, Decimal("1.25")))
        t2 = threading.Thread(target=_diff, args=(d2, Decimal("9.99")))
        t1.start()
        t2.start()
        t1.join(20)
        t2.join(20)
        d1.close()
        d2.close()
        self.assertEqual(len(diff_outs), 2)
        bindings = [row for row in __import__(
            "aurora.risk_adjudicator", fromlist=["read_bindings"]
        ).read_bindings(diff_log) if row["object_name"] == "account"]
        self.assertEqual(len(bindings), 1)
        stored = bindings[0]["canonical_body"]
        self.assertTrue(("1.25" in stored) ^ ("9.99" in stored))
        winner_nav = Decimal("1.25") if "1.25" in stored else Decimal("9.99")
        for nav, item in diff_outs:
            if nav == winner_nav:
                self.assertTrue(item["receipt"]["wrote_now"])
                self.assertNotIn("INPUT_IDENTITY_CONFLICT", item["record"]["blockers"])
            else:
                self.assertFalse(item["receipt"]["wrote_now"])
                self.assertIn("INPUT_IDENTITY_CONFLICT", item["record"]["blockers"])
                self.assertTrue(item["receipt"]["record_present"])
        self.assertEqual(len(self._records(diff_log)), 1)
        reread = [row for row in __import__(
            "aurora.risk_adjudicator", fromlist=["read_bindings"]
        ).read_bindings(diff_log) if row["object_name"] == "account"]
        self.assertEqual(reread[0]["canonical_body"], stored)

    def _replay_in_subprocess(self):
        payload = {
            "decision": _decision(),
            "account": _account(),
            "market": _market(),
            "policy": _policy(),
            "evaluation_at": EVAL,
            "log_path": self.log,
        }
        proc = subprocess.run(
            [sys.executable, os.path.join(ROOT, "tests", "test_risk_adjudicator_r31.py"), "--replay-stdin"],
            input=json.dumps(_enc(payload)),
            text=True,
            capture_output=True,
            cwd=ROOT,
            env={**os.environ, "PYTHONPATH": ROOT},
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        return json.loads(proc.stdout)

    def _install_probes(self):
        from aurora.execution_engine import ExecutionEngine
        from aurora.execution_engine_v2 import ExecutionEngineV2
        from aurora.kernel.binance_exchange import BinanceExchange
        from aurora.ops_controlled_requal import WireTee
        from aurora.portfolio_brain_v2 import PortfolioBrainV2
        from aurora.production_main import BinanceBroker
        import aurora.risk_gate as risk_gate

        self._counts = {
            "futures_create_order": 0,
            "create_order": 0,
            "risk_gate": 0,
            "brain": 0,
            "send": 0,
        }
        counts = self._counts

        def _blocked(counter):
            def _call(*_args, **_kwargs):
                counts[counter] += 1
                raise ProbeBlocked(counter)
            return _call

        self._orig_send = socket.socket.send
        self._orig_sendall = socket.socket.sendall
        self._orig_connect = socket.socket.connect
        self._orig_create_connection = socket.create_connection
        socket.socket.send = _blocked("send")
        socket.socket.sendall = _blocked("send")
        socket.socket.connect = _blocked("send")
        socket.create_connection = _blocked("send")

        self._wire = WireTee
        self._broker = BinanceBroker
        self._exchange = BinanceExchange
        self._engine = ExecutionEngine
        self._engine2 = ExecutionEngineV2
        self._brain_cls = PortfolioBrainV2
        self._orig_futures = WireTee.futures_create_order
        self._orig_create = BinanceBroker.create_order
        self._orig_submit = BinanceExchange.submit_order
        self._orig_place = ExecutionEngine.place_order
        self._orig_place_retry = ExecutionEngineV2._place_order_with_retry
        self._orig_process = PortfolioBrainV2.process
        WireTee.futures_create_order = _blocked("futures_create_order")
        BinanceBroker.create_order = _blocked("create_order")
        BinanceExchange.submit_order = _blocked("futures_create_order")
        ExecutionEngine.place_order = _blocked("futures_create_order")
        ExecutionEngineV2._place_order_with_retry = _blocked("futures_create_order")
        PortfolioBrainV2.process = _blocked("brain")

        self._risk_gate = risk_gate
        self._orig_gate = {}
        for name in dir(risk_gate.RiskGate):
            if name.startswith("_"):
                continue
            attr = getattr(risk_gate.RiskGate, name)
            if callable(attr):
                self._orig_gate[name] = attr
                setattr(risk_gate.RiskGate, name, _blocked("risk_gate"))
        return counts

    def _restore_probes(self):
        socket.socket.send = self._orig_send
        socket.socket.sendall = self._orig_sendall
        socket.socket.connect = self._orig_connect
        socket.create_connection = self._orig_create_connection
        self._wire.futures_create_order = self._orig_futures
        self._broker.create_order = self._orig_create
        self._exchange.submit_order = self._orig_submit
        self._engine.place_order = self._orig_place
        self._engine2._place_order_with_retry = self._orig_place_retry
        self._brain_cls.process = self._orig_process
        for name, attr in self._orig_gate.items():
            setattr(self._risk_gate.RiskGate, name, attr)


class ProbeBlocked(RuntimeError):
    """A write or send probe stopped the call before the real entry."""


class R31IndependentCounterexamples(unittest.TestCase):
    """R31-01～06。这些断言在 9214729 上失败，不是导入失败。"""

    def setUp(self):
        R31AcceptanceTests.setUp(self)

    def tearDown(self):
        R31AcceptanceTests.tearDown(self)

    def _run(self, **kw):
        return R31AcceptanceTests._run(self, **kw)

    def _install_probes(self):
        return R31AcceptanceTests._install_probes(self)

    def _restore_probes(self):
        return R31AcceptanceTests._restore_probes(self)

    def test_r31_01_bad_timestamps_do_not_pass(self):
        cases = (
            ("missing", _account(), "acc-missing-ts"),
            ("garbage", _account(as_of="garbage", account_version="acc-garbage-ts"), "acc-garbage-ts"),
            ("naive", _account(as_of="2026-10-28T00:30:00", account_version="acc-naive"), "acc-naive"),
        )
        cases[0][1].pop("as_of", None)
        for name, account, version in cases:
            with self.subTest(name=name):
                out = self._run(
                    account=account,
                    decision=_decision(decision_key="dec-" + name),
                    market=_market(quote_version="q-" + name),
                    log_path=os.path.join(self.tmp, "ts-" + name + ".sqlite"),
                )
                self.assertNotEqual(out["record"]["risk_state"], "PASS")
                self.assertFalse(out["record"]["new_risk_allowed"])
                self.assertIn("TIMESTAMP_INVALID", out["record"]["blockers"])
                self.assertFalse(out["receipt"]["idempotent"])

    def test_r31_02_unknown_governance_and_bad_positions(self):
        bare = _account()
        del bare["kill"]
        del bare["incident"]
        with self.subTest(name="governance-missing"):
            missing = self._run(
                account=bare,
                log_path=os.path.join(self.tmp, "gov-missing.sqlite"),
            )
            self.assertNotEqual(missing["record"]["risk_state"], "PASS")
            self.assertFalse(missing["record"]["new_risk_allowed"])
            self.assertIn("GOVERNANCE_UNKNOWN", missing["record"]["blockers"])

        with self.subTest(name="governance-unknown"):
            unknown = self._run(
                account=_account(kill="UNKNOWN", incident="UNKNOWN", account_version="acc-gov-u"),
                decision=_decision(decision_key="dec-gov-u"),
                log_path=os.path.join(self.tmp, "gov-unknown.sqlite"),
            )
            self.assertNotEqual(unknown["record"]["risk_state"], "PASS")
            self.assertFalse(unknown["record"]["new_risk_allowed"])
            self.assertIn("GOVERNANCE_UNKNOWN", unknown["record"]["blockers"])

        with self.subTest(name="account-status"):
            bad_status = self._run(
                account=_account(status="garbage", account_version="acc-status"),
                decision=_decision(decision_key="dec-status"),
                log_path=os.path.join(self.tmp, "status.sqlite"),
            )
            self.assertNotEqual(bad_status["record"]["risk_state"], "PASS")
            self.assertIn("ACCOUNT_STATUS_INVALID", bad_status["record"]["blockers"])

        with self.subTest(name="positions"):
            garbage_pos = self._run(
                account=_account(positions="garbage", account_version="acc-pos"),
                decision=_decision(decision_key="dec-pos"),
                log_path=os.path.join(self.tmp, "pos.sqlite"),
            )
            self.assertNotEqual(garbage_pos["record"]["risk_state"], "PASS")
            self.assertFalse(garbage_pos["record"]["new_risk_allowed"])
            self.assertIn("POSITION_MALFORMED", garbage_pos["record"]["blockers"])
            self.assertNotEqual(garbage_pos["record"]["existing_position_protection"], "NOT_APPLICABLE")
            self.assertNotEqual(garbage_pos["record"]["existing_position_protection"], "ACTIVE_CONFIRMED")

    def test_r31_03_submit_flag_and_policy_hash_are_required(self):
        with self.subTest(name="submit-allowed"):
            first = self._run(log_path=os.path.join(self.tmp, "submit.sqlite"))
            altered = _decision()
            altered["submit_allowed"] = True
            second = self._run(
                decision=altered,
                log_path=os.path.join(self.tmp, "submit.sqlite"),
            )
            self.assertNotEqual(second["record"]["risk_state"], "PASS")
            self.assertFalse(second["record"]["new_risk_allowed"])
            self.assertFalse(second["receipt"]["idempotent"])
            self.assertFalse(second["receipt"]["wrote_now"])
            self.assertNotEqual(second["record_canonical"], first["record_canonical"])
            self.assertIn("SUBMIT_NOT_FALSE", second["record"]["blockers"])
            self.assertTrue(first["record"]["submit_allowed"] is False)

        with self.subTest(name="policy-hash"):
            policy = _policy(policy_version="pol-no-hash")
            policy.pop("policy_hash", None)
            omitted = self._run(
                policy=policy,
                decision=_decision(decision_key="dec-no-hash"),
                account=_account(account_version="acc-no-hash"),
                market=_market(quote_version="q-no-hash"),
                log_path=os.path.join(self.tmp, "no-hash.sqlite"),
            )
            self.assertNotEqual(omitted["record"]["risk_state"], "PASS")
            self.assertFalse(omitted["record"]["new_risk_allowed"])
            self.assertFalse(omitted["receipt"]["wrote_now"])
            self.assertIn("POLICY_INCOMPLETE", omitted["record"]["blockers"])

    def test_r31_04_block_does_not_keep_requested_increase(self):
        out = self._run(
            account=_account(as_of="2026-10-27T00:00:00Z", account_version="acc-old"),
            decision=_decision(decision_key="dec-old"),
            market=_market(quote_version="q-old"),
            policy=_policy(
                policy_version="pol-sla-account",
                sla_account_sec=Decimal("60"),
                skew_limit_sec=Decimal("1000000"),
            ),
            log_path=os.path.join(self.tmp, "adjust.sqlite"),
        )
        self.assertEqual(out["record"]["risk_state"], "BLOCK_NEW_RISK")
        self.assertEqual(_num(out["record"]["new_risk"]["allowed"]), Decimal("0"))
        self.assertFalse(out["record"]["new_risk_allowed"])
        self.assertEqual(_num(out["record"]["requested_cluster"]["btc"]), Decimal("1"))
        self.assertEqual(out["record"]["risk_adjusted_delta"].get("status"), "UNAVAILABLE")
        self.assertEqual(out["record"]["risk_adjusted_target"].get("status"), "UNAVAILABLE")
        self.assertNotIn("btc_overlay", out["record"]["risk_adjusted_delta"])
        self.assertNotIn("btc_overlay", out["record"]["risk_adjusted_target"])

        defensive = self._run(
            decision=_defensive_decision(decision_key="dec-def-old"),
            account=_account(as_of="2026-10-27T00:00:00Z", account_version="acc-def-old"),
            market=_market(quote_version="q-def-old"),
            policy=_policy(
                policy_version="pol-sla-def",
                sla_account_sec=Decimal("60"),
                skew_limit_sec=Decimal("1000000"),
            ),
            log_path=os.path.join(self.tmp, "adjust-def.sqlite"),
        )
        self.assertTrue(defensive["record"]["defensive_intent_preserved"])
        self.assertEqual(defensive["record"]["risk_adjusted_delta"].get("status"), "UNAVAILABLE")
        self.assertFalse(defensive["record"]["new_risk_allowed"])

    def test_r31_05_evaluate_decision_boundary(self):
        from aurora.decision_brain import (
            build_normalized_decision_input,
            default_decision_policy,
            evaluate_decision,
        )
        from tests.fixtures.decision_brain_r1_cases import (
            CURRENT_80_10,
            KNOWN_ACCOUNT,
            TREND_L5,
            _base,
        )

        candidate = evaluate_decision(
            build_normalized_decision_input(**_base(
                trend_btc=TREND_L5,
                account_truth=KNOWN_ACCOUNT,
                current_state=CURRENT_80_10,
                as_of=ASOF,
            )),
            default_decision_policy(),
        )
        self.assertEqual(candidate["btc_overlay_action"], "INCREASE_CANDIDATE")
        self.assertFalse(candidate["submit_allowed"])
        self.assertIsInstance(candidate["crypto_beta_cluster"]["btc_request"], float)
        from aurora.risk_adjudicator import adapt_decision_candidate

        raw = self._run(
            decision=candidate,
            log_path=os.path.join(self.tmp, "brain-raw.sqlite"),
        )
        self.assertIn("BINARY_FLOAT", raw["record"]["blockers"])
        self.assertNotEqual(raw["record"]["risk_state"], "PASS")

        adapted = adapt_decision_candidate(candidate)
        out = self._run(
            decision=adapted,
            account=_account(account_version="acc-brain"),
            market=_market(quote_version="q-brain"),
            policy=_policy(policy_version="pol-brain"),
            log_path=os.path.join(self.tmp, "brain-adapted.sqlite"),
        )
        self.assertNotIn("BINARY_FLOAT", out["record"]["blockers"])
        self.assertEqual(out["record"]["decision_boundary"], "evaluate-decision-boundary-v1")
        self.assertEqual(out["record"]["decision_representation"], "decimal-from-str-float-v1")
        self.assertEqual(out["record"]["execution_eligibility"], "DENIED")
        self.assertFalse(out["record"]["submit_allowed"])
        self.assertGreater(_num(out["record"]["requested_cluster"]["btc"]), Decimal("0"))
        self.assertIn(out["record"]["risk_state"], ("PASS", "REDUCED"))
        self.assertTrue(out["receipt"]["wrote_now"])

    def test_r31_05a_non_finite_is_not_null_and_cannot_pass(self):
        import copy
        from aurora.risk_adjudicator import adapt_decision_candidate, read_records

        legal_input = _decision(decision_key="dec-null")
        legal_input["target_state"]["btc_overlay"] = None
        legal_input["delta_proposal"]["btc_overlay"] = None
        legal = adapt_decision_candidate(legal_input)
        self.assertIsNone(legal["candidate"]["target_state"]["btc_overlay"])
        self.assertIsNone(legal["candidate"]["delta_proposal"]["btc_overlay"])
        self.assertFalse(legal.get("non_finite_paths"))
        legal_out = self._run(
            decision=legal,
            log_path=os.path.join(self.tmp, "null-ok.sqlite"),
        )
        self.assertNotIn("NON_FINITE", legal_out["record"]["blockers"])

        samples = (
            ("nan-target", "target_state", float("nan")),
            ("nan-delta", "delta_proposal", float("nan")),
            ("pos-inf-target", "target_state", float("inf")),
            ("neg-inf-delta", "delta_proposal", float("-inf")),
        )
        for name, field, value in samples:
            with self.subTest(name=name):
                raw = _decision(decision_key="dec-" + name)
                raw[field]["btc_overlay"] = value
                adapted = adapt_decision_candidate(copy.deepcopy(raw))
                stored = adapted["candidate"][field]["btc_overlay"]
                self.assertIsInstance(stored, dict)
                self.assertIn(stored.get("$aurora_non_finite"), ("nan", "inf", "-inf"))
                log_path = os.path.join(self.tmp, name + ".sqlite")
                out = self._run(
                    decision=adapted,
                    account=_account(account_version="acc-" + name),
                    market=_market(quote_version="q-" + name),
                    policy=_policy(policy_version="pol-" + name),
                    log_path=log_path,
                )
                self.assertNotEqual(out["record"]["risk_state"], "PASS")
                self.assertFalse(out["record"]["new_risk_allowed"])
                self.assertFalse(out["receipt"]["wrote_now"])
                self.assertFalse(out["receipt"]["record_present"])
                self.assertIn("NON_FINITE", out["record"]["blockers"])
                self.assertEqual(read_records(log_path), [])

    def test_r31_05b_outer_declaration_cannot_bypass_inner_binding(self):
        import copy
        from aurora.risk_adjudicator import adapt_decision_candidate, read_records

        log_path = os.path.join(self.tmp, "boundary-bind.sqlite")
        first = adapt_decision_candidate(_decision())
        opened = self._run(decision=first, log_path=log_path)
        self.assertEqual(opened["record"]["risk_state"], "PASS")
        self.assertTrue(opened["receipt"]["wrote_now"])
        self.assertEqual(opened["record"]["based_on_decision_key"], "dec-v1")
        self.assertEqual(len(read_records(log_path)), 1)

        changed = copy.deepcopy(first)
        changed["candidate"]["target_state"]["btc_overlay"] = Decimal("2")
        changed["candidate"]["delta_proposal"]["btc_overlay"] = Decimal("2")
        conflict = self._run(decision=changed, log_path=log_path)
        self.assertNotEqual(conflict["record"]["risk_state"], "PASS")
        self.assertIn("INPUT_IDENTITY_CONFLICT", conflict["record"]["blockers"])
        self.assertFalse(conflict["receipt"]["wrote_now"])
        self.assertTrue(conflict["receipt"]["record_present"])
        self.assertEqual(len(read_records(log_path)), 1)

        bypasses = (
            ("decision_key", "dec-other"),
            ("source", "AUTHORITATIVE"),
            ("as_of", "2026-10-28T00:45:00Z"),
            ("submit_allowed", True),
        )
        for field, value in bypasses:
            with self.subTest(field=field):
                forged = copy.deepcopy(changed)
                forged[field] = value
                out = self._run(decision=forged, log_path=log_path)
                self.assertNotEqual(out["record"]["risk_state"], "PASS")
                self.assertFalse(out["record"]["new_risk_allowed"])
                self.assertFalse(out["receipt"]["wrote_now"])
                self.assertNotEqual(out["record"]["based_on_decision_key"], value)
                self.assertEqual(len(read_records(log_path)), 1)
                self.assertIn("BOUNDARY_DECLARATION_MISMATCH", out["record"]["blockers"])

        legal = copy.deepcopy(changed)
        legal["decision_key"] = "dec-v2"
        legal["candidate"]["decision_key"] = "dec-v2"
        fresh = self._run(decision=legal, log_path=log_path)
        self.assertNotIn("INPUT_IDENTITY_CONFLICT", fresh["record"]["blockers"])
        self.assertNotIn("BOUNDARY_DECLARATION_MISMATCH", fresh["record"]["blockers"])
        self.assertEqual(fresh["record"]["based_on_decision_key"], "dec-v2")
        self.assertTrue(fresh["receipt"]["wrote_now"])
        self.assertEqual(len(read_records(log_path)), 2)
        self.assertEqual(read_records(log_path)[0]["record_canonical"], opened["record_canonical"])

    def test_r31_06_probes_bind_real_entries_and_block_send(self):
        from aurora.kernel.binance_exchange import BinanceExchange
        from aurora.ops_controlled_requal import WireTee
        from aurora.portfolio_brain_v2 import PortfolioBrainV2
        from aurora.production_main import BinanceBroker
        from aurora.risk_gate import RiskGate

        counts = self._install_probes()
        try:
            probes = (
                ("send", lambda: socket.socket.send(None, b"x"), "send"),
                (
                    "futures_create_order",
                    lambda: WireTee.futures_create_order(
                        object(), symbol="BTCUSDT", side="BUY", type="MARKET", quantity=1
                    ),
                    "futures_create_order",
                ),
                (
                    "create_order",
                    lambda: BinanceBroker.create_order(
                        object(), symbol="BTCUSDT", side="BUY", type="MARKET", quantity=1
                    ),
                    "create_order",
                ),
                (
                    "submit_order",
                    lambda: BinanceExchange.submit_order(object(), object()),
                    "futures_create_order",
                ),
                ("risk_gate", lambda: RiskGate.approve(object(), "LONG", 1), "risk_gate"),
                ("brain", lambda: PortfolioBrainV2.process(object(), [], "BULL", 1), "brain"),
            )
            for name, call, counter in probes:
                with self.subTest(probe=name):
                    before = counts[counter]
                    with self.assertRaises(ProbeBlocked):
                        call()
                    self.assertGreater(counts[counter], before)

            for key in counts:
                counts[key] = 0
            self._run(log_path=os.path.join(self.tmp, "probes.sqlite"))
            self.assertEqual(counts, {key: 0 for key in counts})
        finally:
            self._restore_probes()


def _replay_stdin():
    from aurora.risk_adjudicator import adjudicate_runtime
    payload = _dec_hook(json.loads(sys.stdin.read()))
    out = adjudicate_runtime(
        payload["decision"],
        payload["account"],
        payload["market"],
        payload["policy"],
        evaluation_at=payload["evaluation_at"],
        log_path=payload["log_path"],
    )
    sys.stdout.write(json.dumps({
        "record_canonical": out["record_canonical"],
        "receipt": out["receipt"],
    }))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--replay-stdin":
        _replay_stdin()
    else:
        unittest.main()
