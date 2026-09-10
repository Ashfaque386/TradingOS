"""Organisational memory (spec T021, research R13, FR-032/FR-033).

A thin wrapper over the existing Qdrant infra + embedding pipeline for the ``organization_memory``
collection: past plans, CEO decisions, conflict resolutions, and rejected/failed-strategy
summaries. The CEO planner queries this before planning; a failed/rejected strategy writes a
point here (FR-033). No second memory platform (constitution V).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

from src.core.config import get_settings
from src.memory.embeddings import embed_text

COLLECTION = "organization_memory"


def _client() -> QdrantClient:
    return QdrantClient(url=get_settings().qdrant_url)


def ingest_org_memory(*, kind: str, text: str, payload: dict[str, Any] | None = None) -> str:
    """Store one organisational-memory point. ``kind`` is e.g. ``plan`` / ``decision`` /
    ``conflict`` / ``failed_strategy`` (FR-032/033). Returns the point id."""
    point_id = str(uuid.uuid4())
    vector = embed_text(text)
    _client().upsert(
        collection_name=COLLECTION,
        points=[
            PointStruct(
                id=point_id,
                vector=vector,
                payload={
                    "kind": kind,
                    "text": text,
                    "created_at": datetime.now(UTC).isoformat(),
                    **(payload or {}),
                },
            )
        ],
    )
    return point_id


def query_org_memory(text: str, *, top_k: int = 5) -> list[dict[str, Any]]:
    """Semantic lookup of prior organisational memory relevant to ``text`` (FR-032). Returns
    payloads only; degrades to an empty list on any retrieval error so planning is never
    blocked by a memory-store hiccup."""
    try:
        vector = embed_text(text)
        hits = _client().query_points(collection_name=COLLECTION, query=vector, limit=top_k).points
    except (
        Exception
    ):  # noqa: BLE001 -- memory is advisory; a lookup failure must not block planning
        return []
    return [dict(hit.payload or {}) for hit in hits]
