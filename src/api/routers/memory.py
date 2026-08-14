"""Memory/RAG query API (REL-010 E10.8c).

Wraps the exact `embed_text` + `QdrantClient.query_points` pattern already proven in
src/agents/tools/skills.py's `QdrantStrategyMemorySkill`/`NewsSentimentQuerySkill` -- a thin,
generic read surface over whichever real Qdrant collection is named, not a new memory
implementation. Ungated: this is a read-only semantic-search surface over already-ingested
agent/strategy data, matching every other plain data read in this codebase.

UPDATE 2026-08-14 (REL-059): this module used to advertise itself as "API-087..090", a loose
range that was wrong on half its span -- this file has exactly the 2 routes below, both real:
API-087 (`GET /memory/query`, a close match to the spec'd POST) and API-089
(`GET /memory/collections`). API-088 (`POST /memory/ingest`) and API-090
(`DELETE /memory/{vector_id}`) are confirmed still No -- ingestion/deletion only happen via
direct Qdrant-client calls from agent nodes (src/memory/strategy_memory.py,
src/memory/news_memory.py), never through a public REST route in this file.
"""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from qdrant_client import QdrantClient

from src.core.config import get_settings
from src.memory.collections import COLLECTIONS
from src.memory.embeddings import embed_text

router = APIRouter(prefix="/api/v1/memory", tags=["memory"])


def _qdrant_client() -> QdrantClient:
    return QdrantClient(url=get_settings().qdrant_url)


class MemoryHit(BaseModel):
    score: float
    payload: dict[str, Any] | None


@router.get("/query", response_model=list[MemoryHit])
def query_memory(collection: str, q: str, top_k: int = 5) -> list[MemoryHit]:
    """API-087 (previously also cited "API-088" here, which is actually `POST /memory/ingest`,
    still No -- see the module docstring). `collection` must be one of the real, bootstrapped
    collections (src/memory/collections.py::COLLECTIONS) -- a made-up name 404s rather than
    silently hitting Qdrant with a collection that doesn't exist."""
    if collection not in COLLECTIONS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown collection '{collection}'. Valid collections: {COLLECTIONS}",
        )
    vector = embed_text(q)
    hits = _qdrant_client().query_points(collection_name=collection, query=vector, limit=top_k)
    return [MemoryHit(score=h.score, payload=h.payload) for h in hits.points]


class CollectionStatus(BaseModel):
    name: str
    exists: bool
    points_count: int | None


@router.get("/collections", response_model=list[CollectionStatus])
def list_collections() -> list[CollectionStatus]:
    """API-089 (previously also cited "API-090" here, which is actually
    `DELETE /memory/{vector_id}`, still No -- see the module docstring). Real bootstrap/
    point-count status per collection -- `exists=False` for a collection declared in COLLECTIONS
    but never actually created in Qdrant yet (e.g. `agent_memory`, which nothing in this codebase
    writes to today)."""
    client = _qdrant_client()
    existing = {c.name for c in client.get_collections().collections}
    statuses = []
    for name in COLLECTIONS:
        if name in existing:
            info = client.get_collection(name)
            statuses.append(
                CollectionStatus(name=name, exists=True, points_count=info.points_count)
            )
        else:
            statuses.append(CollectionStatus(name=name, exists=False, points_count=None))
    return statuses
