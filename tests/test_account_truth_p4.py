"""P4 account truth — AT-1 through AT-39.

Red until aurora/account_truth.py exists. Imports stay inside each test so a
missing module is an error, not a semantic assertion failure. The hash test
does not import the module.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

E2_SHA256 = "27f36b3de9b01f89e8dd5d360d7f219345c00bf086652af2a50241ff8440ef84"
E1_SHA256 = "c0f7a700da1e483d6af3621abf1b057eea8177275428dafd7155e85ab68bcdf3"
PLAN = "ab2e872417e43b4665cd16b7a4873f826974f5fc"
ASOF = "2026-10-30T00:00:00Z"
EVAL = "2026-10-30T00:30:00Z"
FORBIDDEN = (
    "trading_cycle",
    "production_main",
    "risk_gate",
    "risk_kernel",
    "execution_engine",
    "portfolio_brain_v2",
    "binance",
    "armed_runtime",
    "sqlite3",
    "socket",
    "urllib",
    "requests",
    "kernel_ledger",
)


def _filter(event_type):
    return {
        "environment": "FIXTURE",
        "account_ref": "acct-1",
        "sub_account_ref": "PRIMARY",
        "event_type": event_type,
        "symbols": [],
    }


def _manifest(event_type):
    filt = _filter(event_type)
    return {
        "window_from": "2026-10-29T00:00:00Z",
        "window_to": "2026-10-30T00:00:00Z",
        "query_filter": filt,
        "pages_fetched": 1,
        "pages_declared": 1,
        "page_end_token": None,
        "truncated": False,
        "retained_from": "2026-10-01T00:00:00Z",
        "zero_event_proof": {"query_filter": copy.deepcopy(filt), "page_end_token": None},
        "events": [],
        "late_known": False,
        "completeness_evidence": None,
        "lineage": {
            "receipt_ref": event_type.lower() + "-rcpt",
            "raw_response_hash": "ab" * 32,
        },
    }


def _policy(**overrides):
    base = {
        "arithmetic_policy_version": "arith-v1",
        "max_input_scale": 8,
        "max_result_scale": 12,
        "max_significant_digits": 18,
        "exponent_min": -18,
        "exponent_max": 18,
        "max_intermediate_digits": 36,
        "max_balance_rows": 32,
        "max_position_rows": 32,
        "max_event_rows": 64,
        "sla_account_sec": "86400",
        "skew_limit_sec": "3600",
        "reconcile_tolerance_btc": "0",
    }
    base.update(overrides)
    return base


def _scope(products, assets, positions):
    return {
        "environment": "FIXTURE",
        "account_ref": "acct-1",
        "sub_account_ref": "PRIMARY",
        "as_of": ASOF,
        "scope_version": "scope-v1",
        "source_claim": "SYNTHETIC",
        "version_claim": "v1",
        "includes_settled_flows": True,
        "products": products,
        "set_completeness": {
            "required_assets": list(assets),
            "observed_assets": list(assets),
            "required_positions": list(positions),
            "observed_positions": list(positions),
            "proof_kind": "EXPLICIT_SET_EQUAL",
            "lineage": {"receipt_ref": "set-rcpt", "raw_response_hash": "cd" * 32},
        },
        "transfers": [],
    }


def _face(amount, products):
    return {
        "amount": amount,
        "asset": "BTC",
        "as_of": ASOF,
        "environment": "FIXTURE",
        "account_ref": "acct-1",
        "sub_account_ref": "PRIMARY",
        "products": list(products),
        "receipt_ref": "venue-rcpt",
        "raw_response_hash": "ee" * 32,
    }


def _ledger(anchors, products, positions=None, liabilities=None):
    return {
        "opening_anchor": anchors,
        "movements": [],
        "ledger_positions": [] if positions is None else positions,
        "liabilities": [] if liabilities is None else liabilities,
        "as_of": ASOF,
        "environment": "FIXTURE",
        "account_ref": "acct-1",
        "sub_account_ref": "PRIMARY",
        "products": list(products),
        "receipt_ref": "ledger-rcpt",
        "raw_response_hash": "ff" * 32,
    }


def _btc_row(total="1", free=None, locked=None):
    row = {
        "product": "SPOT",
        "wallet": "SPOT",
        "asset": "BTC",
        "status": "KNOWN",
    }
    if free is None and locked is None:
        row["free"] = total
        row["locked"] = "0"
        row["total"] = total
    else:
        row["free"] = free
        row["locked"] = locked
        if total is not None:
            row["total"] = total
    return row


def _spot_case(total="1"):
    products = [{"product": "SPOT", "position_mode": "NOT_APPLICABLE", "margin_mode": "NOT_APPLICABLE"}]
    names = ["SPOT"]
    return {
        "scope": _scope(products, ["SPOT|SPOT|BTC"], []),
        "balances": [_btc_row(total)],
        "liabilities": [],
        "positions": [],
        "fee_manifest": _manifest("FEE"),
        "funding_manifest": _manifest("FUNDING"),
        "quotes": {"quote_version": "q-v1", "pairs": []},
        "venue_reported_equity": _face(total, names),
        "ledger_reconstruction": _ledger(
            [{"amount": total, "asset": "BTC", "as_of": ASOF, "anchor_version": "anchor-btc"}],
            names,
        ),
        "binding_state": {"bindings": []},
        "collection_proofs": None,
        "policy": _policy(),
        "evaluation_at": EVAL,
    }


def _run(case):
    from aurora.account_truth import evaluate_account_truth
    return evaluate_account_truth(**case)


def _usdt_pair(price="0.00001"):
    return {"base_asset": "USDT", "quote_asset": "BTC", "price": price}


def _btc_usdt_pair(price="100000"):
    return {"base_asset": "BTC", "quote_asset": "USDT", "price": price}


class P4AccountTruthTests(unittest.TestCase):
    def test_at_00_baseline_hashes_do_not_need_the_module(self):
        for rel, expect in (
            ("aurora/strategy_v2.py", E2_SHA256),
            ("aurora/risk_semantics.py", E1_SHA256),
        ):
            data = open(os.path.join(ROOT, rel), "rb").read()
            self.assertEqual(hashlib.sha256(data).hexdigest(), expect)
        text = open(os.path.join(ROOT, "evidence", "p4_account_truth", "BASELINE.md"), encoding="utf-8").read()
        self.assertIn(PLAN, text)
        self.assertIn(E2_SHA256, text)
        self.assertIn(E1_SHA256, text)
        self.assertIn("NOT YET VERIFIED", text)

    def test_at_positive_full_valuation(self):
        case = self._full_book()
        out = _run(case)
        snap = out["snapshot"]
        self.assertEqual(snap["blockers"], [])
        self.assertTrue(snap["calculation_ok"])
        self.assertEqual(snap["btc_nav"], "0.519")
        self.assertEqual(snap["btc_nav_unit"], "BTC")
        trace = snap["btc_nav_trace"]
        self.assertEqual(trace["spot_equity_btc"], "0.5")
        self.assertEqual(trace["futures_wallet_btc"], "0.01")
        self.assertEqual(trace["unrealized_pnl_btc"], "0.01")
        self.assertEqual(trace["liability_btc"], "0.001")
        self.assertEqual(snap["reconciliation"], "MATCH")
        self.assertEqual(snap["positions"], "KNOWN")
        self._authority_closed(snap)
        self.assertNotIn("ACTIVE_CONFIRMED", str(snap))

    def test_at_btc_amount_is_identity(self):
        case = _spot_case("2")
        case["quotes"]["pairs"] = [{"base_asset": "BTC", "quote_asset": "BTC", "price": "2"}]
        out = _run(case)
        self.assertEqual(out["snapshot"]["btc_nav"], "2")
        self.assertEqual(out["snapshot"]["blockers"], [])
        self._authority_closed(out["snapshot"])

    def test_at_spot_gross_liability_deducted_once(self):
        case = _spot_case("0")
        case["balances"] = [{
            "product": "SPOT", "wallet": "SPOT", "asset": "USDT",
            "free": "1000", "locked": "0", "total": "1000", "status": "KNOWN",
        }]
        case["liabilities"] = [{"asset": "USDT", "amount": "100", "status": "KNOWN"}]
        case["scope"]["set_completeness"]["required_assets"] = ["SPOT|SPOT|USDT"]
        case["scope"]["set_completeness"]["observed_assets"] = ["SPOT|SPOT|USDT"]
        case["quotes"]["pairs"] = [_usdt_pair()]
        case["venue_reported_equity"]["amount"] = "0.009"
        case["ledger_reconstruction"]["opening_anchor"] = [
            {"amount": "1000", "asset": "USDT", "as_of": ASOF, "anchor_version": "anchor-usdt"},
        ]
        case["ledger_reconstruction"]["liabilities"] = [
            {"asset": "USDT", "amount": "100", "status": "KNOWN"},
        ]
        out = _run(case)
        snap = out["snapshot"]
        self.assertEqual(snap["blockers"], [])
        self.assertEqual(snap["btc_nav_trace"]["spot_equity_btc"], "0.01")
        self.assertEqual(snap["btc_nav_trace"]["liability_btc"], "0.001")
        self.assertEqual(snap["btc_nav"], "0.009")

    def test_at_01_missing_account_ref(self):
        for value in (None, ""):
            with self.subTest(value=value):
                case = _spot_case()
                if value is None:
                    case["scope"].pop("account_ref")
                else:
                    case["scope"]["account_ref"] = value
                snap = _run(case)["snapshot"]
                self.assertIn("ACCOUNT_IDENTITY_UNFIXED", snap["blockers"])
                self.assertIsNone(snap["btc_nav"])

    def test_at_02_same_version_conflict_does_not_replace_hash(self):
        first = _run(_spot_case())
        binding = first["binding_proposal"]["proposed_binding"]
        state = {"bindings": [copy.deepcopy(binding)]}
        replay = _run(_spot_case())
        replay_case = _spot_case()
        replay_case["binding_state"] = copy.deepcopy(state)
        replayed = _run(replay_case)
        self.assertEqual(replayed["binding_proposal"]["action"], "REPLAY")
        changed = _spot_case("1.5")
        changed["binding_state"] = copy.deepcopy(state)
        out = _run(changed)
        proposal = out["binding_proposal"]
        self.assertEqual(proposal["action"], "CONFLICT")
        self.assertEqual(proposal["prior_content_hash"], binding["content_hash"])
        self.assertEqual(proposal["existing_bindings"][0]["content_hash"], binding["content_hash"])
        self.assertIsNone(proposal["proposed_binding"])
        self.assertIn("INPUT_IDENTITY_CONFLICT", out["snapshot"]["blockers"])
        self.assertIsNone(out["snapshot"]["btc_nav"])
        self.assertEqual(replay["snapshot"]["binding_proposal"], "APPEND")

    def test_at_03_new_version_appends_and_keeps_existing_set(self):
        first = _run(_spot_case())
        old = first["binding_proposal"]["proposed_binding"]
        case = _spot_case()
        case["scope"]["version_claim"] = "v2"
        case["binding_state"] = {"bindings": [copy.deepcopy(old)]}
        out = _run(case)
        proposal = out["binding_proposal"]
        self.assertEqual(proposal["action"], "APPEND")
        self.assertEqual(proposal["existing_bindings"], [old])
        self.assertEqual(proposal["existing_bindings"][0]["canonical_body"], old["canonical_body"])
        self.assertNotEqual(proposal["proposed_binding"]["declaration_key"], old["declaration_key"])
        self.assertIsNone(proposal["prior_content_hash"])

    def test_at_04_missing_btc_row_is_not_zero(self):
        case = _spot_case()
        case["balances"] = []
        snap = _run(case)["snapshot"]
        self.assertIn("BALANCE_INCOMPLETE", snap["blockers"])
        self.assertIsNone(snap["btc_nav"])
        self.assertNotEqual(snap["btc_nav"], "0")

    def test_at_05_explicit_zero_stays_known_while_other_gaps_block(self):
        case = _spot_case("0")
        proof = case["scope"]["set_completeness"]
        proof["required_assets"] = ["SPOT|SPOT|BTC", "SPOT|SPOT|ETH"]
        proof["observed_assets"] = ["SPOT|SPOT|BTC", "SPOT|SPOT|ETH"]
        snap = _run(case)["snapshot"]
        self.assertIn("BALANCE_INCOMPLETE", snap["blockers"])
        self.assertIsNone(snap["btc_nav"])
        btc = [row for row in snap["balances"] if row.get("asset") == "BTC"]
        self.assertEqual(btc[0]["total"], "0")

    def test_at_06_negative_wallet_balance(self):
        case = _spot_case("-1")
        snap = _run(case)["snapshot"]
        self.assertIn("SIGN_MISMATCH", snap["blockers"])
        self.assertIsNone(snap["btc_nav"])

    def test_at_07_positions_missing(self):
        case = _spot_case()
        case["positions"] = None
        snap = _run(case)["snapshot"]
        self.assertIn("POSITION_UNKNOWN", snap["blockers"])
        self.assertEqual(snap["positions"], "UNKNOWN")
        self.assertIsNone(snap["btc_nav"])

    def test_at_08_positions_garbage_is_not_flat(self):
        case = _spot_case()
        case["positions"] = "garbage"
        snap = _run(case)["snapshot"]
        self.assertIn("POSITION_MALFORMED", snap["blockers"])
        self.assertEqual(snap["positions"], "MALFORMED")
        self.assertNotEqual(snap["positions"], "FLAT")

    def test_at_09_explicit_zero_qty_is_flat(self):
        case = _spot_case()
        case["positions"] = [self._position(qty="0")]
        case["scope"]["products"].append(
            {"product": "USDS_M", "position_mode": "ONE_WAY", "margin_mode": "CROSS"}
        )
        for face in (case["venue_reported_equity"], case["ledger_reconstruction"]):
            face["products"] = ["SPOT", "USDS_M"]
        proof = case["scope"]["set_completeness"]
        proof["required_positions"] = ["USDS_M|BTCUSDT|LONG"]
        proof["observed_positions"] = ["USDS_M|BTCUSDT|LONG"]
        snap = _run(case)["snapshot"]
        self.assertEqual(snap["positions"], "FLAT")
        self.assertNotIn("ACTIVE_CONFIRMED", str(snap))
        self.assertNotIn("POSITION_UNKNOWN", snap["blockers"])

    def test_at_10_hedge_legs_without_mode(self):
        case = self._futures_case()
        case["scope"]["products"][0]["position_mode"] = None
        case["positions"] = [
            self._position(side="LONG", qty="0.1"),
            self._position(side="SHORT", qty="0.2"),
        ]
        proof = case["scope"]["set_completeness"]
        proof["required_positions"] = ["USDS_M|BTCUSDT|LONG", "USDS_M|BTCUSDT|SHORT"]
        proof["observed_positions"] = ["USDS_M|BTCUSDT|LONG", "USDS_M|BTCUSDT|SHORT"]
        snap = _run(case)["snapshot"]
        self.assertIn("POSITION_MODE_UNKNOWN", snap["blockers"])
        self.assertIsNone(snap["btc_nav"])

    def test_at_11_fee_manifest_missing_is_not_zero(self):
        case = _spot_case()
        case["fee_manifest"] = None
        snap = _run(case)["snapshot"]
        self.assertIn("FEE_UNKNOWN", snap["blockers"])
        self.assertIsNone(snap["btc_nav"])
        self.assertNotEqual(snap["fee_manifest"]["total"], "0")

    def test_at_12_fee_page_not_finished(self):
        case = _spot_case()
        case["fee_manifest"]["page_end_token"] = "next"
        snap = _run(case)["snapshot"]
        self.assertIn("FEE_INCOMPLETE", snap["blockers"])
        self.assertEqual(snap["fee_manifest"]["status"], "INCOMPLETE")

    def test_at_13_funding_missing_does_not_read_e0_zero(self):
        case = _spot_case()
        case["funding_manifest"] = None
        snap = _run(case)["snapshot"]
        self.assertIn("FUNDING_UNKNOWN", snap["blockers"])
        self.assertNotEqual(snap["funding_manifest"]["total"], "0")
        self.assertIsNone(snap["btc_nav"])

    def test_at_14_truncation_and_partial_late_stay_partial(self):
        truncated = _spot_case()
        truncated["funding_manifest"]["retained_from"] = "2026-10-29T12:00:00Z"
        snap = _run(truncated)["snapshot"]
        self.assertIn("FUNDING_INCOMPLETE", snap["blockers"])
        self.assertEqual(snap["funding_manifest"]["status"], "INCOMPLETE")

        late = _spot_case()
        late["funding_manifest"]["late_known"] = True
        late["evaluation_at"] = "2026-12-01T00:00:00Z"
        late_snap = _run(late)["snapshot"]
        self.assertEqual(late_snap["funding_manifest"]["status"], "PARTIAL_LATE")
        self.assertIn("FUNDING_INCOMPLETE", late_snap["blockers"])
        self.assertNotEqual(late_snap["funding_manifest"]["status"], "COMPLETE")

        pages_only = _spot_case()
        pages_only["funding_manifest"]["late_known"] = True
        pages_only["funding_manifest"]["page_end_token"] = None
        pages_only["funding_manifest"]["truncated"] = False
        self.assertEqual(_run(pages_only)["snapshot"]["funding_manifest"]["status"], "PARTIAL_LATE")

        repaired = _spot_case()
        manifest = repaired["funding_manifest"]
        manifest["late_known"] = True
        manifest["completeness_evidence"] = {
            "window_from": manifest["window_from"],
            "window_to": manifest["window_to"],
            "query_filter": copy.deepcopy(manifest["query_filter"]),
            "pages_fetched": 1,
            "pages_declared": 1,
            "page_end_token": None,
            "truncated": False,
            "retained_from": "2026-10-01T00:00:00Z",
            "re_queried_full": True,
        }
        repaired_snap = _run(repaired)["snapshot"]
        self.assertEqual(repaired_snap["funding_manifest"]["status"], "COMPLETE")
        self.assertNotIn("FUNDING_INCOMPLETE", repaired_snap["blockers"])
        self.assertEqual(repaired_snap["btc_nav"], "1")

    def test_at_15_quote_direction(self):
        missing = _spot_case("0")
        missing["balances"] = [
            _btc_row("0"),
            {"product": "SPOT", "wallet": "SPOT", "asset": "ETH", "free": "1", "locked": "0", "total": "1", "status": "KNOWN"},
        ]
        proof = missing["scope"]["set_completeness"]
        proof["required_assets"] = ["SPOT|SPOT|BTC", "SPOT|SPOT|ETH"]
        proof["observed_assets"] = ["SPOT|SPOT|BTC", "SPOT|SPOT|ETH"]
        snap = _run(missing)["snapshot"]
        self.assertIn("QUOTE_UNPINNED", snap["blockers"])
        self.assertIsNone(snap["btc_nav"])

        forward = self._usdt_nav_case(_usdt_pair("0.00001"))
        self.assertEqual(_run(forward)["snapshot"]["btc_nav"], "0.01")
        inverse = self._usdt_nav_case(_btc_usdt_pair("100000"))
        self.assertEqual(_run(inverse)["snapshot"]["btc_nav"], "0.01")
        flipped = self._usdt_nav_case(_usdt_pair("100000"))
        flipped_nav = _run(flipped)["snapshot"]["btc_nav"]
        self.assertNotEqual(flipped_nav, "0.01")
        self.assertEqual(flipped_nav, "100000000")

    def test_at_16_unpinned_price_rejected(self):
        case = _spot_case("0")
        case["balances"] = [{
            "product": "SPOT", "wallet": "SPOT", "asset": "ETH",
            "free": "2", "locked": "0", "total": "2", "status": "KNOWN",
            "unpinned_price": "0.05",
        }]
        proof = case["scope"]["set_completeness"]
        proof["required_assets"] = ["SPOT|SPOT|ETH"]
        proof["observed_assets"] = ["SPOT|SPOT|ETH"]
        snap = _run(case)["snapshot"]
        self.assertIn("NAV_PARTIAL_REJECTED", snap["blockers"])
        self.assertIsNone(snap["btc_nav"])

    def test_at_17_non_finite_is_not_washed_to_null(self):
        for raw, marker in ((float("nan"), "nan"), (float("inf"), "inf"), (float("-inf"), "-inf")):
            with self.subTest(marker=marker):
                case = _spot_case()
                case["balances"][0]["total"] = raw
                snap = _run(case)["snapshot"]
                self.assertIn("NON_FINITE", snap["blockers"])
                self.assertIsNone(snap["btc_nav"])
                self.assertTrue(snap["non_finite"])
                self.assertEqual(snap["non_finite"][0]["marker"], marker)
                self.assertNotEqual(snap["balances"], None)

    def test_at_18_legal_null_quote_stays_null(self):
        case = _spot_case("1")
        case["balances"].append({
            "product": "SPOT", "wallet": "SPOT", "asset": "ETH",
            "free": "0", "locked": "0", "total": "0", "status": "KNOWN",
        })
        proof = case["scope"]["set_completeness"]
        proof["required_assets"] = ["SPOT|SPOT|BTC", "SPOT|SPOT|ETH"]
        proof["observed_assets"] = ["SPOT|SPOT|BTC", "SPOT|SPOT|ETH"]
        case["quotes"]["pairs"] = [{"base_asset": "ETH", "quote_asset": "BTC", "price": None}]
        snap = _run(case)["snapshot"]
        self.assertNotIn("NON_FINITE", snap["blockers"])
        self.assertEqual(snap["quotes"]["pairs"][0]["price"], None)
        self.assertEqual(snap["btc_nav"], "1")
        self.assertFalse(snap["non_finite"])

    def test_at_19_bad_timestamps(self):
        missing = _spot_case()
        missing["scope"].pop("as_of")
        garbage = _spot_case()
        garbage["scope"]["as_of"] = "garbage"
        naive = _spot_case()
        naive["scope"]["as_of"] = "2026-10-30T00:00:00"
        for case in (missing, garbage, naive):
            snap = _run(case)["snapshot"]
            self.assertIn("TIMESTAMP_INVALID", snap["blockers"])
            self.assertIsNone(snap["btc_nav"])

    def test_at_20_future_timestamp(self):
        case = _spot_case()
        case["scope"]["as_of"] = "2026-10-30T02:00:00Z"
        case["venue_reported_equity"]["as_of"] = case["scope"]["as_of"]
        case["ledger_reconstruction"]["as_of"] = case["scope"]["as_of"]
        snap = _run(case)["snapshot"]
        self.assertIn("FUTURE_TIMESTAMP", snap["blockers"])

    def test_at_21_sla_and_skew(self):
        late = _spot_case()
        late["policy"]["sla_account_sec"] = "60"
        late["evaluation_at"] = "2026-10-30T02:00:00Z"
        self.assertIn("SLA_EXCEEDED", _run(late)["snapshot"]["blockers"])
        skew = _spot_case()
        skew["quotes"]["as_of"] = "2026-10-28T00:00:00Z"
        skew["policy"]["skew_limit_sec"] = "3600"
        self.assertIn("SKEW_EXCEEDED", _run(skew)["snapshot"]["blockers"])

    def test_at_22_null_sla_is_incomplete_policy(self):
        case = _spot_case()
        case["policy"]["sla_account_sec"] = None
        snap = _run(case)["snapshot"]
        self.assertIn("POLICY_INCOMPLETE", snap["blockers"])
        self.assertIsNone(snap["btc_nav"])

    def test_at_23_one_face_unknown(self):
        case = _spot_case()
        case["venue_reported_equity"] = None
        snap = _run(case)["snapshot"]
        self.assertIn("RECONCILE_UNAVAILABLE", snap["blockers"])
        self.assertEqual(snap["reconciliation"], "UNAVAILABLE")
        self.assertIsNone(snap["btc_nav"])

    def test_at_24_mismatch_does_not_write_back(self):
        case = _spot_case("1")
        case["venue_reported_equity"]["amount"] = "2"
        snap = _run(case)["snapshot"]
        self.assertIn("RECONCILE_MISMATCH", snap["blockers"])
        self.assertEqual(snap["reconciliation"], "MISMATCH")
        self.assertEqual(snap["venue_reported_equity"]["amount"], "2")
        self.assertIsNone(snap["btc_nav"])

    def test_at_25_synthetic_cannot_become_authority(self):
        case = self._full_book()
        case["scope"]["source_claim"] = "SYNTHETIC"
        snap = _run(case)["snapshot"]
        self.assertTrue(snap["calculation_ok"])
        self._authority_closed(snap)
        self.assertEqual(snap["order_intent"], "ABSENT")
        self.assertEqual(snap["execution_eligibility"], "DENIED")

    def test_at_26_same_input_same_policy_same_bytes(self):
        from aurora.account_truth import canonical_dumps
        case = self._full_book()
        first = canonical_dumps(_run(case)["snapshot"])
        time.sleep(0.01)
        second = canonical_dumps(_run(copy.deepcopy(case))["snapshot"])
        self.assertEqual(first, second)

    def test_at_27_static_scan(self):
        path = os.path.join(ROOT, "aurora", "account_truth.py")
        source = open(path, encoding="utf-8").read()
        tree = ast.parse(source)
        modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
        blob = "\n".join(modules).lower() + "\n" + source.lower()
        for banned in FORBIDDEN:
            self.assertNotIn(banned, blob)
        self.assertNotIn("datetime.now", source)
        self.assertNotIn("time.time", source)
        cycle = open(os.path.join(ROOT, "aurora", "trading_cycle.py"), encoding="utf-8").read()
        adjudicator = open(os.path.join(ROOT, "aurora", "risk_adjudicator.py"), encoding="utf-8").read()
        self.assertNotIn("evaluate_account_truth", cycle)
        self.assertNotIn("account_truth", adjudicator)

    def test_at_28_wallet_once_and_quote_orientations(self):
        one = self._futures_flat_pnl()
        snap = _run(one)["snapshot"]
        self.assertEqual(snap["blockers"], [])
        self.assertEqual(snap["btc_nav_trace"]["unrealized_pnl_settle"]["USDT"], "0")
        self.assertEqual(snap["btc_nav_trace"]["futures_equity_settle"]["USDT"], "1000")
        self.assertEqual(snap["btc_nav"], "0.01")

        two = self._futures_flat_pnl()
        two["positions"].append(self._position(symbol="ETHUSDT", qty="1", entry="1", mark="1"))
        proof = two["scope"]["set_completeness"]
        proof["required_positions"] = ["USDS_M|BTCUSDT|LONG", "USDS_M|ETHUSDT|LONG"]
        proof["observed_positions"] = ["USDS_M|BTCUSDT|LONG", "USDS_M|ETHUSDT|LONG"]
        two_snap = _run(two)["snapshot"]
        self.assertEqual(two_snap["btc_nav_trace"]["futures_equity_settle"]["USDT"], "1000")
        self.assertEqual(two_snap["btc_nav"], "0.01")

        repeated = self._futures_flat_pnl()
        repeated["positions"][0]["wallet_balance_settle"] = "1000"
        self.assertIn("DOUBLE_COUNT", _run(repeated)["snapshot"]["blockers"])

        notion = self._futures_flat_pnl()
        notion["positions"][0]["include_notional"] = True
        notion_snap = _run(notion)["snapshot"]
        self.assertIn("NOTIONAL_REJECTED", notion_snap["blockers"])
        self.assertIsNone(notion_snap["btc_nav"])

        forward = self._futures_flat_pnl()
        self.assertEqual(_run(forward)["snapshot"]["btc_nav"], "0.01")
        inverse = self._futures_flat_pnl(pair=_btc_usdt_pair("100000"))
        self.assertEqual(_run(inverse)["snapshot"]["btc_nav"], "0.01")
        flipped = self._futures_flat_pnl(pair=_usdt_pair("100000"))
        flipped["venue_reported_equity"]["amount"] = "100000000"
        self.assertEqual(_run(flipped)["snapshot"]["btc_nav"], "100000000")

        long_up = self._futures_flat_pnl()
        long_up["positions"][0]["mark_price"] = "110000"
        long_up["ledger_reconstruction"]["ledger_positions"][0]["mark_price"] = "110000"
        long_up["venue_reported_equity"]["amount"] = "0.02"
        long_snap = _run(long_up)["snapshot"]
        self.assertEqual(long_snap["btc_nav_trace"]["unrealized_pnl_settle"]["USDT"], "1000")
        self.assertEqual(long_snap["btc_nav"], "0.02")

        short = self._futures_flat_pnl()
        short["positions"][0]["side"] = "SHORT"
        short["ledger_reconstruction"]["ledger_positions"][0]["side"] = "SHORT"
        short["positions"][0]["mark_price"] = "110000"
        short["ledger_reconstruction"]["ledger_positions"][0]["mark_price"] = "110000"
        short["scope"]["set_completeness"]["required_positions"] = ["USDS_M|BTCUSDT|SHORT"]
        short["scope"]["set_completeness"]["observed_positions"] = ["USDS_M|BTCUSDT|SHORT"]
        short["venue_reported_equity"]["amount"] = "0"
        short_snap = _run(short)["snapshot"]
        self.assertEqual(short_snap["btc_nav_trace"]["unrealized_pnl_settle"]["USDT"], "-1000")
        self.assertEqual(short_snap["btc_nav"], "0")
        self.assertNotIn("SIGN_MISMATCH", short_snap["blockers"])

    def test_at_29_settled_flows_are_not_applied_again(self):
        case = _spot_case()
        case["fee_manifest"]["events"] = [{
            "event_type": "FEE",
            "stable_id": "fee-1",
            "amount": "1",
            "asset": "BTC",
            "apply_to_nav": True,
        }]
        case["fee_manifest"]["zero_event_proof"] = None
        snap = _run(case)["snapshot"]
        self.assertIn("DOUBLE_COUNT", snap["blockers"])
        self.assertIsNone(snap["btc_nav"])

    def test_at_30_mixed_wallets_and_one_sided_transfer(self):
        mixed = _spot_case()
        mixed["balances"][0]["mix_into"] = ["SPOT", "USDS_M"]
        self.assertIn("DOUBLE_COUNT", _run(mixed)["snapshot"]["blockers"])
        both = _spot_case()
        both["balances"][0]["count_free_and_total"] = True
        self.assertIn("DOUBLE_COUNT", _run(both)["snapshot"]["blockers"])
        transfer = _spot_case()
        transfer["scope"]["transfers"] = [{
            "transfer_id": "t1",
            "asset": "BTC",
            "amount": "0.1",
            "direction": "IN",
            "wallet": "SPOT",
        }]
        snap = _run(transfer)["snapshot"]
        self.assertIn("TRANSFER_SCOPE_UNBALANCED", snap["blockers"])
        self.assertIsNone(snap["btc_nav"])

    def test_at_31_set_proof_and_duplicates(self):
        missing = _spot_case()
        missing["scope"]["set_completeness"] = None
        self.assertIn("SET_INCOMPLETE", _run(missing)["snapshot"]["blockers"])
        dup = _spot_case()
        dup["balances"].append(_btc_row("1"))
        snap = _run(dup)["snapshot"]
        self.assertIn("DUPLICATE_ROW", snap["blockers"])
        self.assertIsNone(snap["btc_nav"])

    def test_at_32_self_reported_authority_is_not_established(self):
        missing = self._full_book()
        missing["scope"]["source_claim"] = "AUTHORITATIVE"
        missing["collection_proofs"] = None
        snap = _run(missing)["snapshot"]
        self.assertIn("AUTHORITY_NOT_PROVABLE", snap["blockers"])
        self._authority_closed(snap)
        bad = self._full_book()
        bad["scope"]["source_claim"] = "AUTHORITATIVE"
        bad["collection_proofs"] = {
            "receipt_ref": "rcpt",
            "account_binding": {
                "environment": "FIXTURE",
                "account_ref": "someone-else",
                "sub_account_ref": "PRIMARY",
            },
            "raw_response_hash": "12" * 32,
            "verifier": "fixture-verifier",
            "verified_at": ASOF,
        }
        bad_snap = _run(bad)["snapshot"]
        self.assertIn("COLLECTION_PROOF_INVALID", bad_snap["blockers"])
        self._authority_closed(bad_snap)

    def test_at_33_window_states(self):
        failed = _spot_case()
        failed["funding_manifest"]["pages_fetched"] = 1
        failed["funding_manifest"]["pages_declared"] = 2
        self.assertEqual(_run(failed)["snapshot"]["funding_manifest"]["status"], "INCOMPLETE")
        cut = _spot_case()
        cut["funding_manifest"]["retained_from"] = "2026-10-29T06:00:00Z"
        self.assertEqual(_run(cut)["snapshot"]["funding_manifest"]["status"], "INCOMPLETE")
        zero = _spot_case()
        zero_snap = _run(zero)["snapshot"]
        self.assertEqual(zero_snap["funding_manifest"]["status"], "COMPLETE")
        self.assertEqual(zero_snap["funding_manifest"]["total"], "0")
        absent = _spot_case()
        absent["funding_manifest"] = None
        absent_snap = _run(absent)["snapshot"]
        self.assertEqual(absent_snap["funding_manifest"]["status"], "UNKNOWN")
        self.assertIsNone(absent_snap["funding_manifest"]["total"])

    def test_at_34_event_identity_and_late_version(self):
        clash = _spot_case()
        clash["fee_manifest"]["zero_event_proof"] = None
        clash["fee_manifest"]["events"] = [
            {"event_type": "FEE", "stable_id": "9", "amount": "1", "asset": "BTC"},
            {"event_type": "FEE", "stable_id": "9", "amount": "2", "asset": "BTC"},
        ]
        snap = _run(clash)["snapshot"]
        self.assertIn("EVENT_IDENTITY_CONFLICT", snap["blockers"])
        self.assertEqual(len(snap["fee_manifest"]["events"]), 2)

        cross = _spot_case()
        cross["fee_manifest"]["zero_event_proof"] = None
        cross["funding_manifest"]["zero_event_proof"] = None
        cross["fee_manifest"]["events"] = [
            {"event_type": "FEE", "stable_id": "9", "amount": "1", "asset": "BTC"},
        ]
        cross["funding_manifest"]["events"] = [
            {"event_type": "FUNDING", "stable_id": "9", "amount": "4", "asset": "BTC"},
        ]
        cross_snap = _run(cross)["snapshot"]
        self.assertNotIn("EVENT_IDENTITY_CONFLICT", cross_snap["blockers"])
        self.assertEqual(len(cross_snap["fee_manifest"]["events"]), 1)
        self.assertEqual(len(cross_snap["funding_manifest"]["events"]), 1)

        old = _run(_spot_case())["binding_proposal"]["proposed_binding"]
        late = _spot_case()
        late["scope"]["version_claim"] = "v2"
        late["funding_manifest"]["late_known"] = True
        late["evaluation_at"] = "2027-01-01T00:00:00Z"
        late["binding_state"] = {"bindings": [copy.deepcopy(old)]}
        late_out = _run(late)
        self.assertEqual(late_out["snapshot"]["funding_manifest"]["status"], "PARTIAL_LATE")
        self.assertNotEqual(late_out["snapshot"]["funding_manifest"]["status"], "COMPLETE")
        self.assertEqual(late_out["binding_proposal"]["existing_bindings"][0]["canonical_body"], old["canonical_body"])

    def test_at_35_evaluation_time_does_not_hide_conflict(self):
        first = _run(_spot_case())
        binding = first["binding_proposal"]["proposed_binding"]
        changed = _spot_case("3")
        changed["evaluation_at"] = "2026-10-30T00:40:00Z"
        changed["binding_state"] = {"bindings": [copy.deepcopy(binding)]}
        out = _run(changed)
        self.assertEqual(out["binding_proposal"]["action"], "CONFLICT")
        absent = _spot_case()
        absent["binding_state"] = None
        refused = _run(absent)
        self.assertEqual(refused["binding_proposal"]["action"], "REFUSED")
        self.assertIn("BINDING_STATE_ABSENT", refused["snapshot"]["blockers"])
        self.assertIsNone(refused["binding_proposal"]["proposed_binding"])

    def test_at_36_independence_and_mark_move_without_cash(self):
        shared = self._futures_flat_pnl()
        shared["ledger_reconstruction"]["receipt_ref"] = shared["venue_reported_equity"]["receipt_ref"]
        shared["ledger_reconstruction"]["raw_response_hash"] = shared["venue_reported_equity"]["raw_response_hash"]
        self.assertIn("RECONCILE_NOT_INDEPENDENT", _run(shared)["snapshot"]["blockers"])

        copied = self._futures_flat_pnl()
        copied["ledger_reconstruction"]["copied_from"] = "account_snapshot"
        self.assertEqual(_run(copied)["snapshot"]["reconciliation"], "NOT_INDEPENDENT")

        borrowed = self._futures_flat_pnl()
        borrowed["ledger_reconstruction"]["pnl_source"] = "VENUE"
        borrowed["ledger_reconstruction"]["ledger_positions"] = None
        self.assertIn("RECONCILE_NOT_INDEPENDENT", _run(borrowed)["snapshot"]["blockers"])

        before = self._futures_flat_pnl()
        before_snap = _run(before)["snapshot"]
        after = self._futures_flat_pnl()
        after["positions"][0]["mark_price"] = "110000"
        after["ledger_reconstruction"]["ledger_positions"][0]["mark_price"] = "110000"
        after["venue_reported_equity"]["amount"] = "0.02"
        after_snap = _run(after)["snapshot"]
        self.assertEqual(self._asset_amount(before_snap, "USDT"), "1000")
        self.assertEqual(self._asset_amount(after_snap, "USDT"), "2000")
        self.assertEqual(after_snap["ledger_reconstruction"]["cash_reconstructed"][0]["amount"], "1000")
        self.assertEqual(after_snap["blockers"], [])

    def test_at_37_tolerance_and_scope(self):
        equal = _spot_case("1")
        equal["venue_reported_equity"]["amount"] = "1.00000001"
        equal["policy"]["reconcile_tolerance_btc"] = "0.00000001"
        equal_snap = _run(equal)["snapshot"]
        self.assertEqual(equal_snap["reconciliation"], "MATCH")
        self.assertEqual(equal_snap["btc_nav"], "1")

        greater = _spot_case("1")
        greater["venue_reported_equity"]["amount"] = "1.00000002"
        greater["policy"]["reconcile_tolerance_btc"] = "0.00000001"
        greater_snap = _run(greater)["snapshot"]
        self.assertEqual(greater_snap["reconciliation"], "MISMATCH")
        self.assertEqual(greater_snap["venue_reported_equity"]["amount"], "1.00000002")

        negative = _spot_case()
        negative["policy"]["reconcile_tolerance_btc"] = "-0.01"
        self.assertIn("TOLERANCE_INVALID", _run(negative)["snapshot"]["blockers"])

        scope = _spot_case()
        scope["venue_reported_equity"]["account_ref"] = "other"
        self.assertIn("SCOPE_MISMATCH", _run(scope)["snapshot"]["blockers"])

    def test_at_38_numeric_limits_and_policy_identity(self):
        third = self._usdt_nav_case(_btc_usdt_pair("3"), total="1")
        self.assertIn("PRECISION_INSUFFICIENT", _run(third)["snapshot"]["blockers"])

        scale = _spot_case()
        scale["balances"][0]["total"] = "1.123456789"
        scale["balances"][0]["free"] = "1.123456789"
        scale["policy"]["max_input_scale"] = 8
        self.assertIn("PRECISION_INSUFFICIENT", _run(scale)["snapshot"]["blockers"])

        huge = _spot_case()
        huge["balances"][0]["total"] = "1e1000000"
        self.assertIn("NUMERIC_LIMIT", _run(huge)["snapshot"]["blockers"])
        tiny = _spot_case()
        tiny["balances"][0]["total"] = "1e-1000000"
        self.assertIn("NUMERIC_LIMIT", _run(tiny)["snapshot"]["blockers"])

        carry = _spot_case()
        carry["balances"][0].pop("total")
        carry["balances"][0]["free"] = "500"
        carry["balances"][0]["locked"] = "500"
        carry["policy"]["max_significant_digits"] = 3
        carry["policy"]["max_intermediate_digits"] = 3
        self.assertIn("NUMERIC_LIMIT", _run(carry)["snapshot"]["blockers"])

        product = self._futures_flat_pnl()
        product["positions"][0]["qty"] = "123456"
        product["positions"][0]["entry_price"] = "1"
        product["positions"][0]["mark_price"] = "123457"
        product["policy"]["max_intermediate_digits"] = 10
        self.assertIn("NUMERIC_LIMIT", _run(product)["snapshot"]["blockers"])

        from aurora.account_truth import canonical_dumps
        left = self._full_book()
        right = self._full_book()
        right["policy"]["arithmetic_policy_version"] = "arith-v2"
        self.assertNotEqual(
            canonical_dumps(_run(left)["snapshot"]),
            canonical_dumps(_run(right)["snapshot"]),
        )

    def test_at_39_negative_pnl_negative_nav_and_bad_quote(self):
        pnl = self._futures_flat_pnl()
        pnl["balances"][0]["free"] = "2000"
        pnl["balances"][0]["total"] = "2000"
        pnl["positions"][0]["side"] = "SHORT"
        pnl["positions"][0]["mark_price"] = "110000"
        pnl["ledger_reconstruction"]["opening_anchor"][0]["amount"] = "2000"
        pnl["ledger_reconstruction"]["ledger_positions"][0]["side"] = "SHORT"
        pnl["ledger_reconstruction"]["ledger_positions"][0]["mark_price"] = "110000"
        pnl["scope"]["set_completeness"]["required_positions"] = ["USDS_M|BTCUSDT|SHORT"]
        pnl["scope"]["set_completeness"]["observed_positions"] = ["USDS_M|BTCUSDT|SHORT"]
        pnl["venue_reported_equity"]["amount"] = "0.01"
        pnl_snap = _run(pnl)["snapshot"]
        self.assertEqual(pnl_snap["btc_nav_trace"]["unrealized_pnl_settle"]["USDT"], "-1000")
        self.assertNotIn("SIGN_MISMATCH", pnl_snap["blockers"])
        self.assertEqual(pnl_snap["btc_nav"], "0.01")

        negative = self._futures_flat_pnl()
        negative["balances"][0]["free"] = "100"
        negative["balances"][0]["total"] = "100"
        negative["positions"][0]["side"] = "SHORT"
        negative["positions"][0]["mark_price"] = "110000"
        negative["ledger_reconstruction"]["opening_anchor"][0]["amount"] = "100"
        negative["ledger_reconstruction"]["ledger_positions"][0]["side"] = "SHORT"
        negative["ledger_reconstruction"]["ledger_positions"][0]["mark_price"] = "110000"
        negative["scope"]["set_completeness"]["required_positions"] = ["USDS_M|BTCUSDT|SHORT"]
        negative["scope"]["set_completeness"]["observed_positions"] = ["USDS_M|BTCUSDT|SHORT"]
        negative["venue_reported_equity"]["amount"] = "-0.009"
        nav = _run(negative)["snapshot"]
        self.assertEqual(nav["blockers"], [])
        self.assertEqual(nav["btc_nav"], "-0.009")
        self.assertTrue(nav["calculation_ok"])
        self.assertNotIn("SIGN_MISMATCH", nav["blockers"])
        self._authority_closed(nav)

        for price in ("0", "-1"):
            with self.subTest(price=price):
                bad = self._usdt_nav_case(_usdt_pair(price))
                self.assertIn("QUOTE_INVALID", _run(bad)["snapshot"]["blockers"])

    def _authority_closed(self, snap):
        self.assertEqual(snap["reality_authority"], "NOT_ESTABLISHED")
        self.assertEqual(snap["account_authority"], "NOT_ESTABLISHED")
        self.assertFalse(snap["new_risk_usable"])

    def _asset_amount(self, snap, asset):
        rows = snap["ledger_reconstruction"]["mark_equity"]
        return next(row["amount"] for row in rows if row["asset"] == asset)

    def _position(self, **overrides):
        row = {
            "symbol": "BTCUSDT",
            "contract_kind": "LINEAR_PERPETUAL",
            "side": "LONG",
            "qty": "0.1",
            "contract_multiplier": "1",
            "entry_price": "100000",
            "mark_price": "100000",
            "settlement_asset": "USDT",
            "product": "USDS_M",
            "status": "KNOWN",
        }
        row.update(overrides)
        return row

    def _futures_case(self):
        products = [{"product": "USDS_M", "position_mode": "ONE_WAY", "margin_mode": "CROSS"}]
        names = ["USDS_M"]
        return {
            "scope": _scope(products, ["USDS_M|USDS_M|USDT"], ["USDS_M|BTCUSDT|LONG"]),
            "balances": [{
                "product": "USDS_M", "wallet": "USDS_M", "asset": "USDT",
                "free": "1000", "locked": "0", "total": "1000", "status": "KNOWN",
            }],
            "liabilities": [],
            "positions": [self._position()],
            "fee_manifest": _manifest("FEE"),
            "funding_manifest": _manifest("FUNDING"),
            "quotes": {"quote_version": "q-v1", "pairs": [_usdt_pair()]},
            "venue_reported_equity": _face("0.01", names),
            "ledger_reconstruction": _ledger(
                [{"amount": "1000", "asset": "USDT", "as_of": ASOF, "anchor_version": "anchor-usdt"}],
                names,
                positions=[self._position()],
            ),
            "binding_state": {"bindings": []},
            "collection_proofs": None,
            "policy": _policy(),
            "evaluation_at": EVAL,
        }

    def _futures_flat_pnl(self, pair=None):
        case = self._futures_case()
        if pair is not None:
            case["quotes"]["pairs"] = [pair]
        return case

    def _usdt_nav_case(self, pair, total="1000"):
        case = _spot_case("0")
        case["balances"] = [{
            "product": "SPOT", "wallet": "SPOT", "asset": "USDT",
            "free": total, "locked": "0", "total": total, "status": "KNOWN",
        }]
        case["scope"]["set_completeness"]["required_assets"] = ["SPOT|SPOT|USDT"]
        case["scope"]["set_completeness"]["observed_assets"] = ["SPOT|SPOT|USDT"]
        case["quotes"]["pairs"] = [pair]
        if pair["base_asset"] == "USDT" and pair["price"] == "0.00001" and total == "1000":
            nav = "0.01"
        elif pair["base_asset"] == "BTC" and pair["price"] == "100000" and total == "1000":
            nav = "0.01"
        elif pair["base_asset"] == "USDT" and pair["price"] == "100000" and total == "1000":
            nav = "100000000"
        elif pair["price"] == "3" and total == "1":
            nav = "0"
        else:
            nav = "0"
        case["venue_reported_equity"]["amount"] = nav
        case["ledger_reconstruction"]["opening_anchor"] = [
            {"amount": total, "asset": "USDT", "as_of": ASOF, "anchor_version": "anchor-usdt"},
        ]
        return case

    def _full_book(self):
        products = [
            {"product": "SPOT", "position_mode": "NOT_APPLICABLE", "margin_mode": "NOT_APPLICABLE"},
            {"product": "USDS_M", "position_mode": "ONE_WAY", "margin_mode": "CROSS"},
        ]
        names = ["SPOT", "USDS_M"]
        position = self._position(mark="110000")
        scope = _scope(
            products,
            ["SPOT|SPOT|BTC", "USDS_M|USDS_M|USDT"],
            ["USDS_M|BTCUSDT|LONG"],
        )
        return {
            "scope": scope,
            "balances": [
                _btc_row(None, free="0.2", locked="0.3"),
                {
                    "product": "USDS_M", "wallet": "USDS_M", "asset": "USDT",
                    "free": "1000", "locked": "0", "total": "1000", "status": "KNOWN",
                },
            ],
            "liabilities": [{"asset": "USDT", "amount": "100", "status": "KNOWN"}],
            "positions": [position],
            "fee_manifest": _manifest("FEE"),
            "funding_manifest": _manifest("FUNDING"),
            "quotes": {"quote_version": "q-v1", "pairs": [_usdt_pair()]},
            "venue_reported_equity": _face("0.519", names),
            "ledger_reconstruction": _ledger(
                [
                    {"amount": "0.5", "asset": "BTC", "as_of": ASOF, "anchor_version": "anchor-btc"},
                    {"amount": "1000", "asset": "USDT", "as_of": ASOF, "anchor_version": "anchor-usdt"},
                ],
                names,
                positions=[self._position(mark="110000")],
                liabilities=[{"asset": "USDT", "amount": "100", "status": "KNOWN"}],
            ),
            "binding_state": {"bindings": []},
            "collection_proofs": None,
            "policy": _policy(),
            "evaluation_at": EVAL,
        }
