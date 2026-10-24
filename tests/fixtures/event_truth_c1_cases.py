"""P2-C.1 Event Truth — CONTRACT FIXTURES (not acceptance authority)."""

from __future__ import annotations

from typing import Any, Dict

# Timestamps (ms) for deterministic replay
T0 = 1_725_000_000_000  # baseline
T1 = T0 + 60_000
T2 = T0 + 120_000
T3 = T0 + 180_000

CPI_KEY = "US_CPI_2026_08"
BLS = "BLS"
FED = "FED"
BEA = "BEA"

CPI_V1_OBS: Dict[str, Any] = {
    "event_key": CPI_KEY,
    "source_id": BLS,
    "event_class": "CPI",
    "title": "US CPI August 2026",
    "factual_claim": "Headline CPI YoY 3.2%",
    "event_time": "2026-08-01T00:00:00Z",
    "source_published_at": "2026-09-10T12:30:00Z",
    "actual_value": 3.2,
    "previous_value": 3.0,
    "payload": {"actual_yoy": 3.2, "period": "2026-08"},
}

CPI_V2_OBS: Dict[str, Any] = {
    "event_key": CPI_KEY,
    "source_id": BLS,
    "event_class": "CPI",
    "title": "US CPI August 2026 (Revised)",
    "factual_claim": "Headline CPI YoY revised to 3.4%",
    "event_time": "2026-08-01T00:00:00Z",
    "source_published_at": "2026-09-12T14:00:00Z",
    "actual_value": 3.4,
    "previous_value": 3.0,
    "revised_previous_value": 3.1,
    "payload": {"actual_yoy": 3.4, "period": "2026-08", "revision": True},
}

FED_CONFLICT_OBS: Dict[str, Any] = {
    "event_key": CPI_KEY,
    "source_id": FED,
    "event_class": "CPI",
    "title": "Fed comment on CPI",
    "factual_claim": "Fed cites CPI YoY 2.8%",
    "event_time": "2026-08-01T00:00:00Z",
    "source_published_at": "2026-09-10T13:00:00Z",
    "actual_value": 2.8,
    "payload": {"actual_yoy": 2.8, "period": "2026-08"},
}

REPOST_DOCS = [
    {"document_id": f"repost-{i}", "evidence_cluster_id": "BLS:US_CPI_2026_08"}
    for i in range(20)
]
