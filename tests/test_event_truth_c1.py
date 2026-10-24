"""P2-C.1 Event Truth Foundation — C1-1..C1-10 acceptance authority."""
from __future__ import annotations

import ast
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from aurora.event_truth import (  # noqa: E402
    CAP_TRUTH,
    CONFLICT_STATE,
    EventTruthLedger,
    LookaheadViolation,
    SOURCE_REGISTRY,
    cluster_documents,
    corroboration_count,
    evaluate_source_fetch,
    get_source_registry,
    resolve_consensus_fields,
)
from tests.fixtures.event_truth_c1_cases import (  # noqa: E402
    BLS,
    CPI_KEY,
    CPI_V1_OBS,
    CPI_V2_OBS,
    FED,
    FED_CONFLICT_OBS,
    REPOST_DOCS,
    T0,
    T1,
    T2,
    T3,
)


class IntegrityTests(unittest.TestCase):
    def test_no_execution_imports(self):
        path = os.path.join(ROOT, "aurora", "event_truth.py")
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
                self.fail(f"event_truth imports forbidden module: {imp}")

    def test_source_registry_four_official(self):
        reg = get_source_registry()
        self.assertEqual(set(reg.keys()), {"FED", "BLS", "BEA", "SEC"})
        for entry in reg.values():
            self.assertEqual(entry["authority_type"], "OFFICIAL")
            self.assertTrue(entry["enabled"])


class C1AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.ledger = EventTruthLedger()

    def test_c1_1_official_first_release_creates_v1(self):
        """C1-1: official first release → event_key + version=1."""
        out = self.ledger.ingest_observation(CPI_V1_OBS, observed_at_ms=T1)
        self.assertEqual(out["result"], "CREATED")
        rec = out["event_record"]
        self.assertEqual(rec["event_key"], CPI_KEY)
        self.assertEqual(rec["event_version"], 1)
        self.assertEqual(rec["revision_type"], "INITIAL")
        self.assertEqual(rec["capability"], CAP_TRUTH)
        self.assertIn("first_observed_at", rec)
        self.assertIn("last_observed_at", rec)

    def test_c1_2_duplicate_payload_idempotent(self):
        """C1-2: same payload re-fetch → IDEMPOTENT, no v2."""
        self.ledger.ingest_observation(CPI_V1_OBS, observed_at_ms=T1)
        out = self.ledger.ingest_observation(CPI_V1_OBS, observed_at_ms=T2)
        self.assertEqual(out["result"], "IDEMPOTENT")
        chain = self.ledger.chains[CPI_KEY]
        self.assertEqual(len(chain), 1)
        self.assertEqual(chain[0]["event_version"], 1)

    def test_c1_3_official_revision_appends_v2(self):
        """C1-3: real revision → append v2, v1 preserved."""
        self.ledger.ingest_observation(CPI_V1_OBS, observed_at_ms=T1)
        out = self.ledger.append_revision(CPI_KEY, CPI_V2_OBS, observed_at_ms=T2)
        self.assertEqual(out["result"], "CREATED")
        self.assertEqual(out["event_record"]["event_version"], 2)
        chain = self.ledger.chains[CPI_KEY]
        self.assertEqual(len(chain), 2)
        self.assertEqual(chain[0]["actual_value"], 3.2)
        self.assertEqual(chain[1]["actual_value"], 3.4)
        self.assertEqual(chain[1]["supersedes_version"], 1)

    def test_c1_4_retraction_appends_not_delete(self):
        """C1-4: RETRACTION → append RETRACTED revision, history kept."""
        self.ledger.ingest_observation(CPI_V1_OBS, observed_at_ms=T1)
        out = self.ledger.append_retraction(CPI_KEY, observed_at_ms=T2, source_id=BLS)
        self.assertEqual(out["result"], "CREATED")
        rec = out["event_record"]
        self.assertTrue(rec["retracted"])
        self.assertEqual(rec["revision_type"], "RETRACTION")
        chain = self.ledger.chains[CPI_KEY]
        self.assertEqual(len(chain), 2)
        self.assertFalse(chain[0]["retracted"])

    def test_c1_5_as_of_before_revision_sees_old_only(self):
        """C1-5: as_of before revision → only old version."""
        self.ledger.ingest_observation(CPI_V1_OBS, observed_at_ms=T1)
        self.ledger.append_revision(CPI_KEY, CPI_V2_OBS, observed_at_ms=T3)
        at_t2 = self.ledger.truth_as_of(CPI_KEY, T2)
        self.assertIsNotNone(at_t2)
        self.assertEqual(at_t2["event_version"], 1)
        self.assertEqual(at_t2["actual_value"], 3.2)
        at_t3 = self.ledger.truth_as_of(CPI_KEY, T3)
        self.assertEqual(at_t3["event_version"], 2)

    def test_c1_6_backdated_revision_lookahead_rejected(self):
        """C1-6: inject later revision at old decision_time → LOOKAHEAD_REJECTED."""
        self.ledger.ingest_observation(CPI_V1_OBS, observed_at_ms=T1)
        backdated = dict(CPI_V2_OBS)
        backdated["first_observed_at"] = "2026-09-10T08:00:00Z"  # before T1 chain head
        with self.assertRaises(LookaheadViolation):
            self.ledger.append_revision(CPI_KEY, backdated, observed_at_ms=T3)

    def test_c1_7_reposts_do_not_increase_corroboration(self):
        """C1-7: 20 reposts same cluster → corroboration_count unchanged."""
        clusters = cluster_documents(REPOST_DOCS)
        self.assertEqual(len(clusters), 1)
        ids = [d["evidence_cluster_id"] for d in REPOST_DOCS]
        self.assertEqual(corroboration_count(ids), 1)

    def test_c1_8_conflicting_authorities_conflict(self):
        """C1-8: two authoritative sources conflict → CONFLICT, not silent pick."""
        self.ledger.ingest_observation(CPI_V1_OBS, observed_at_ms=T1)
        out = self.ledger.ingest_observation(FED_CONFLICT_OBS, observed_at_ms=T2)
        self.assertEqual(out["result"], "CONFLICT")
        self.assertEqual(out["state"], CONFLICT_STATE)
        chain = self.ledger.chains[CPI_KEY]
        self.assertEqual(len(chain), 1)

    def test_c1_9_fetch_failure_not_empty_events(self):
        """C1-9: source fetch failure → SOURCE_ERROR, not silent no-event."""
        out = evaluate_source_fetch(source_id=BLS, fetch_status="error")
        self.assertEqual(out["source_health"], "SOURCE_ERROR")
        self.assertEqual(out["truth_state"], "UNKNOWN")
        self.assertIsNone(out["events"])
        self.assertNotEqual(out["observation_state"], "NO_EVENT_OBSERVED")

    def test_c1_10_no_consensus_expected_unknown(self):
        """C1-10: no independent consensus source → expected/surprise null."""
        out = self.ledger.ingest_observation(CPI_V1_OBS, observed_at_ms=T1)
        rec = out["event_record"]
        self.assertIsNone(rec["expected_value"])
        self.assertIsNone(rec["surprise"])
        self.assertEqual(rec["consensus_truth_state"], "UNKNOWN")
        exp, surprise, state = resolve_consensus_fields(
            actual_value=3.2,
            consensus_source_id=None,
            consensus_observed_at_ms=None,
            expected_value=3.0,
        )
        self.assertIsNone(exp)
        self.assertIsNone(surprise)
        self.assertEqual(state, "UNKNOWN")


class TruthSnapshotTests(unittest.TestCase):
    def test_truth_as_of_all_respects_first_observed(self):
        ledger = EventTruthLedger()
        ledger.ingest_observation(CPI_V1_OBS, observed_at_ms=T1)
        ledger.append_revision(CPI_KEY, CPI_V2_OBS, observed_at_ms=T3)
        snap = ledger.truth_as_of_all(T2)
        self.assertEqual(len(snap), 1)
        self.assertEqual(snap[0]["event_version"], 1)


if __name__ == "__main__":
    unittest.main()
