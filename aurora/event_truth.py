"""P2-C.1 Event Truth Foundation — read-only, append-only, as-of replayable.

NOT impact scoring. NOT priced-in. NOT boost eligibility. NOT execution.

FROZEN:
  first_observed_at is the hard boundary for historical replay
  revisions are append-only — never overwrite prior versions
  fetch failure ≠ no event observed
  expected_value / surprise require independent consensus truth source
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

CAP_TRUTH = "READ-ONLY-TRUTH"
STAGE_CANDIDATE = "EXTRACTED_CANDIDATE"
STAGE_TRUTH = "EVENT_TRUTH"

SOURCE_HEALTH = (
    "NO_EVENT_OBSERVED",
    "SOURCE_NOT_CONNECTED",
    "SOURCE_STALE",
    "SOURCE_ERROR",
    "UNKNOWN",
)

CONFLICT_STATE = "CONFLICT"

FORBIDDEN_C1_FIELDS = frozenset({
    "impact_btc",
    "impact_eth",
    "priced_in",
    "boost_eligibility",
    "action_state",
    "evidence_grade",
})

# P2-C.1 v1 — narrow official registry (not RSS flood)
SOURCE_REGISTRY: Dict[str, Dict[str, Any]] = {
    "FED": {
        "source_id": "FED",
        "authority_type": "OFFICIAL",
        "domain": "federalreserve.gov",
        "event_classes": ["FOMC", "FED_SPEECH", "POLICY"],
        "parser_version": "p2-c1-v1",
        "timezone": "America/New_York",
        "freshness_policy": {"max_stale_minutes": 120},
        "enabled": True,
    },
    "BLS": {
        "source_id": "BLS",
        "authority_type": "OFFICIAL",
        "domain": "bls.gov",
        "event_classes": ["CPI", "NFP", "PPI", "EMPLOYMENT"],
        "parser_version": "p2-c1-v1",
        "timezone": "America/New_York",
        "freshness_policy": {"max_stale_minutes": 180},
        "enabled": True,
    },
    "BEA": {
        "source_id": "BEA",
        "authority_type": "OFFICIAL",
        "domain": "bea.gov",
        "event_classes": ["PCE", "GDP", "PERSONAL_INCOME"],
        "parser_version": "p2-c1-v1",
        "timezone": "America/New_York",
        "freshness_policy": {"max_stale_minutes": 180},
        "enabled": True,
    },
    "SEC": {
        "source_id": "SEC",
        "authority_type": "OFFICIAL",
        "domain": "sec.gov",
        "event_classes": ["FILING", "ENFORCEMENT", "ETF", "REGULATION"],
        "parser_version": "p2-c1-v1",
        "timezone": "America/New_York",
        "freshness_policy": {"max_stale_minutes": 240},
        "enabled": True,
    },
}


class LookaheadViolation(ValueError):
    """Revision or observation violates first_observed_at boundary."""


class EventTruthError(ValueError):
    """General event truth contract violation."""


def _iso_to_ms(iso: Optional[str]) -> Optional[int]:
    if not iso:
        return None
    try:
        normalized = iso.replace("Z", "+00:00")
        return int(datetime.fromisoformat(normalized).timestamp() * 1000)
    except (TypeError, ValueError, OSError):
        return None


def _ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def payload_hash(payload: Dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]


def corroboration_count(clusters: List[str]) -> int:
    """Unique independent evidence clusters — not URL/repost count."""
    return len(set(c for c in clusters if c))


def cluster_documents(documents: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """Group document ids by evidence_cluster_id."""
    out: Dict[str, List[str]] = {}
    for doc in documents:
        cid = doc.get("evidence_cluster_id") or doc.get("cluster_id") or "unknown"
        out.setdefault(cid, []).append(doc.get("document_id") or doc.get("id") or "?")
    return out


def resolve_consensus_fields(
    *,
    actual_value: Optional[float],
    consensus_source_id: Optional[str],
    consensus_observed_at_ms: Optional[int],
    expected_value: Optional[float] = None,
) -> Tuple[Optional[float], Optional[float], str]:
    """expected_value / surprise only with independent consensus truth source."""
    if not consensus_source_id or consensus_observed_at_ms is None:
        return None, None, "UNKNOWN"
    if expected_value is None:
        return None, None, "UNKNOWN"
    surprise = None
    if actual_value is not None:
        surprise = actual_value - expected_value
    return expected_value, surprise, "KNOWN"


def build_canonical_event_record(
    *,
    event_key: str,
    event_version: int,
    source_id: str,
    event_class: str,
    title: str,
    factual_claim: str,
    event_time: str,
    source_published_at: str,
    first_observed_at: str,
    last_observed_at: str,
    payload: Dict[str, Any],
    revision_type: str = "INITIAL",
    supersedes_version: Optional[int] = None,
    retracted: bool = False,
    evidence_cluster_id: Optional[str] = None,
    actual_value: Optional[float] = None,
    previous_value: Optional[float] = None,
    revised_previous_value: Optional[float] = None,
    consensus_source_id: Optional[str] = None,
    consensus_observed_at_ms: Optional[int] = None,
    expected_value_input: Optional[float] = None,
    stage: str = STAGE_TRUTH,
) -> Dict[str, Any]:
    if stage == STAGE_TRUTH and source_id not in SOURCE_REGISTRY:
        raise EventTruthError(f"unknown source_id: {source_id}")

    exp, surprise, consensus_state = resolve_consensus_fields(
        actual_value=actual_value,
        consensus_source_id=consensus_source_id,
        consensus_observed_at_ms=consensus_observed_at_ms,
        expected_value=expected_value_input,
    )

    return {
        "capability": CAP_TRUTH,
        "stage": stage,
        "event_key": event_key,
        "event_version": event_version,
        "supersedes_version": supersedes_version,
        "payload_hash": payload_hash(payload),
        "revision_type": revision_type,
        "retracted": retracted,
        "event_time": event_time,
        "source_published_at": source_published_at,
        "first_observed_at": first_observed_at,
        "last_observed_at": last_observed_at,
        "event_class": event_class,
        "title": title,
        "factual_claim": factual_claim,
        "source_id": source_id,
        "evidence_cluster_id": evidence_cluster_id or f"{source_id}:{event_key}",
        "actual_value": actual_value,
        "previous_value": previous_value,
        "revised_previous_value": revised_previous_value,
        "expected_value": exp,
        "surprise": surprise,
        "consensus_truth_state": consensus_state,
        "payload": payload,
    }


class EventTruthLedger:
    """Append-only revision chain with as-of replay."""

    def __init__(self) -> None:
        self._chains: Dict[str, List[Dict[str, Any]]] = {}
        self._payload_index: Dict[str, Tuple[str, int]] = {}  # hash -> (key, version)
        self._conflicts: List[Dict[str, Any]] = []

    @property
    def chains(self) -> Dict[str, List[Dict[str, Any]]]:
        return deepcopy(self._chains)

    def _chain(self, event_key: str) -> List[Dict[str, Any]]:
        return self._chains.setdefault(event_key, [])

    def ingest_observation(
        self,
        observation: Dict[str, Any],
        *,
        observed_at_ms: int,
    ) -> Dict[str, Any]:
        """Ingest official observation — may create v1 or idempotent return."""
        for field in FORBIDDEN_C1_FIELDS:
            if field in observation:
                raise EventTruthError(f"P2-C.1 forbids field in truth ingest: {field}")

        event_key = observation["event_key"]
        source_id = observation["source_id"]
        payload = dict(observation.get("payload") or {})
        ph = payload_hash(payload)

        if ph in self._payload_index:
            key, ver = self._payload_index[ph]
            existing = self._chains[key][ver - 1]
            return {
                "result": "IDEMPOTENT",
                "event_record": deepcopy(existing),
            }

        chain = self._chain(event_key)
        first_obs = observation.get("first_observed_at")
        first_obs_ms = _iso_to_ms(first_obs) or observed_at_ms
        if first_obs_ms > observed_at_ms:
            raise LookaheadViolation("first_observed_at cannot be after ingest wall time")

        if chain:
            last = chain[-1]
            last_obs_ms = _iso_to_ms(last["first_observed_at"]) or 0
            if first_obs_ms < last_obs_ms and observation.get("revision_type") != "INITIAL":
                raise LookaheadViolation(
                    "backdated revision before prior first_observed_at"
                )

        # Conflict: same event_key, different official actual at same version attempt
        if chain and observation.get("revision_type", "INITIAL") == "INITIAL":
            prev = chain[-1]
            if (
                not prev.get("retracted")
                and observation.get("actual_value") is not None
                and prev.get("actual_value") is not None
                and observation.get("actual_value") != prev.get("actual_value")
                and observation.get("source_id") != prev.get("source_id")
            ):
                self._conflicts.append({
                    "event_key": event_key,
                    "sources": [prev.get("source_id"), source_id],
                    "state": CONFLICT_STATE,
                })
                return {"result": "CONFLICT", "state": CONFLICT_STATE}

        version = len(chain) + 1
        rev_type = observation.get("revision_type") or ("INITIAL" if version == 1 else "REVISION")
        supersedes = version - 1 if version > 1 else None

        record = build_canonical_event_record(
            event_key=event_key,
            event_version=version,
            source_id=source_id,
            event_class=observation.get("event_class", "UNKNOWN"),
            title=observation.get("title", ""),
            factual_claim=observation.get("factual_claim", ""),
            event_time=observation.get("event_time", _ms_to_iso(observed_at_ms)),
            source_published_at=observation.get(
                "source_published_at", _ms_to_iso(observed_at_ms)
            ),
            first_observed_at=first_obs or _ms_to_iso(first_obs_ms),
            last_observed_at=_ms_to_iso(observed_at_ms),
            payload=payload,
            revision_type=rev_type,
            supersedes_version=supersedes,
            retracted=bool(observation.get("retracted")),
            evidence_cluster_id=observation.get("evidence_cluster_id"),
            actual_value=observation.get("actual_value"),
            previous_value=observation.get("previous_value"),
            revised_previous_value=observation.get("revised_previous_value"),
            consensus_source_id=observation.get("consensus_source_id"),
            consensus_observed_at_ms=observation.get("consensus_observed_at_ms"),
            expected_value_input=observation.get("expected_value"),
            stage=observation.get("stage", STAGE_TRUTH),
        )

        chain.append(record)
        self._payload_index[ph] = (event_key, version)
        return {"result": "CREATED", "event_record": deepcopy(record)}

    def append_revision(
        self,
        event_key: str,
        observation: Dict[str, Any],
        *,
        observed_at_ms: int,
    ) -> Dict[str, Any]:
        """Append new version — never mutates prior versions."""
        observation = dict(observation)
        observation["event_key"] = event_key
        observation.setdefault("revision_type", "REVISION")
        return self.ingest_observation(observation, observed_at_ms=observed_at_ms)

    def append_retraction(
        self,
        event_key: str,
        *,
        observed_at_ms: int,
        source_id: str,
        title: str = "RETRACTION",
    ) -> Dict[str, Any]:
        chain = self._chain(event_key)
        if not chain:
            raise EventTruthError("cannot retract unknown event_key")
        last = chain[-1]
        obs = {
            "event_key": event_key,
            "source_id": source_id,
            "event_class": last.get("event_class"),
            "title": title,
            "factual_claim": f"Retraction of {event_key} v{last['event_version']}",
            "revision_type": "RETRACTION",
            "retracted": True,
            "payload": {"retracts_version": last["event_version"]},
            "actual_value": last.get("actual_value"),
        }
        return self.ingest_observation(obs, observed_at_ms=observed_at_ms)

    def truth_as_of(
        self,
        event_key: str,
        as_of_ms: int,
    ) -> Optional[Dict[str, Any]]:
        """Return latest version visible at as_of (first_observed_at <= as_of)."""
        chain = self._chain(event_key)
        visible = [
            r for r in chain
            if (_iso_to_ms(r.get("first_observed_at")) or 0) <= as_of_ms
        ]
        if not visible:
            return None
        return deepcopy(visible[-1])

    def truth_as_of_all(self, as_of_ms: int) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for key in self._chains:
            rec = self.truth_as_of(key, as_of_ms)
            if rec:
                out.append(rec)
        return out


def evaluate_source_fetch(
    *,
    source_id: str,
    fetch_status: str,
    events: Optional[List[Dict[str, Any]]] = None,
    last_success_at_ms: Optional[int] = None,
    now_ms: Optional[int] = None,
) -> Dict[str, Any]:
    """Source health is fact — fetch failure ≠ no events in world."""
    now_ms = now_ms or int(datetime.now(timezone.utc).timestamp() * 1000)
    reg = SOURCE_REGISTRY.get(source_id)
    if not reg or not reg.get("enabled"):
        return {
            "source_id": source_id,
            "source_health": "SOURCE_NOT_CONNECTED",
            "truth_state": "UNKNOWN",
            "events": None,
            "observation_state": "SOURCE_NOT_CONNECTED",
        }

    if fetch_status in ("error", "timeout", "denied"):
        return {
            "source_id": source_id,
            "source_health": "SOURCE_ERROR",
            "truth_state": "UNKNOWN",
            "events": None,
            "observation_state": "SOURCE_ERROR",
        }

    if fetch_status == "not_connected":
        return {
            "source_id": source_id,
            "source_health": "SOURCE_NOT_CONNECTED",
            "truth_state": "UNKNOWN",
            "events": None,
            "observation_state": "SOURCE_NOT_CONNECTED",
        }

    max_stale = (reg.get("freshness_policy") or {}).get("max_stale_minutes", 180)
    if last_success_at_ms and (now_ms - last_success_at_ms) > max_stale * 60_000:
        return {
            "source_id": source_id,
            "source_health": "SOURCE_STALE",
            "truth_state": "UNKNOWN",
            "events": events if events is not None else None,
            "observation_state": "SOURCE_STALE",
        }

    if not events:
        return {
            "source_id": source_id,
            "source_health": "NO_EVENT_OBSERVED",
            "truth_state": "OK",
            "events": [],
            "observation_state": "NO_EVENT_OBSERVED",
        }

    return {
        "source_id": source_id,
        "source_health": "NO_EVENT_OBSERVED",
        "truth_state": "OK",
        "events": events,
        "observation_state": "OK",
    }


def get_source_registry() -> Dict[str, Dict[str, Any]]:
    return deepcopy(SOURCE_REGISTRY)
