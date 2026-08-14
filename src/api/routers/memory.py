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

UPDATE 2026-08-14 (REL-062): API-088/090 built below, thin wrappers over the real, already-
tested `ingest_strategy_outcome()` (src/memory/strategy_memory.py) and a genuine new
delete-by-point-id call against the real Qdrant client -- the closest existing precedent
(`src/memory/collections.py::delete_collection`) only ever drops a whole collection, not one
point, so this is real new code against the Qdrant client, not just a route. Both are gated
(SA/PM/RM, the same "operational, equivalent-weight action" role set as this session's other
real write/trigger endpoints) -- unlike the read-only routes above, these can pollute or erase
the real RAG memory the agent pipeline itself reads from.
"""

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from qdrant_client import QdrantClient

from src.api.deps import require_role
from src.core.config import get_settings
from src.core.security import ROLE_PORTFOLIO_MANAGER, ROLE_RISK_MANAGER, ROLE_SYSTEM_ADMINISTRATOR
from src.memory.collections import COLLECTIONS
from src.memory.embeddings import embed_text
from src.memory.strategy_memory import ingest_strategy_outcome
from src.models.user import User

router = APIRouter(prefix="/api/v1/memory", tags=["memory"])

_can_manage_memory = require_role(
    ROLE_SYSTEM_ADMINISTRATOR, ROLE_PORTFOLIO_MANAGER, ROLE_RISK_MANAGER, audit_denials=True
)


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


class IngestOutcomeRequest(BaseModel):
    strategy_id: uuid.UUID
    strategy_version_id: uuid.UUID
    hypothesis: str
    code: str
    asset_class: str
    sharpe_ratio: float
    max_drawdown: float
    status: Literal["active", "deprecated", "archived"]
    failure_reason: str | None = None


class IngestOutcomeResponse(BaseModel):
    point_id: str


@router.post("/ingest", response_model=IngestOutcomeResponse, status_code=201)
def ingest_outcome(
    body: IngestOutcomeRequest, _user: User = Depends(_can_manage_memory)
) -> IngestOutcomeResponse:
    """API-088. A thin wrapper over the real, already-tested `ingest_strategy_outcome()`
    (src/memory/strategy_memory.py) -- deliberately scoped to strategy/backtest outcomes only,
    matching the SRS's literal wording, not `ingest_code_template()`."""
    point_id = ingest_strategy_outcome(
        strategy_id=str(body.strategy_id),
        strategy_version_id=str(body.strategy_version_id),
        hypothesis=body.hypothesis,
        code=body.code,
        asset_class=body.asset_class,
        sharpe_ratio=body.sharpe_ratio,
        max_drawdown=body.max_drawdown,
        status=body.status,
        failure_reason=body.failure_reason,
    )
    return IngestOutcomeResponse(point_id=point_id)


class DeleteVectorResponse(BaseModel):
    deleted: bool
    vector_id: str
    collection: str


@router.delete("/{vector_id}", response_model=DeleteVectorResponse)
def delete_vector(
    vector_id: str, collection: str, _user: User = Depends(_can_manage_memory)
) -> DeleteVectorResponse:
    """API-090. `collection` is required and validated against the real, bootstrapped
    collections (src/memory/collections.py::COLLECTIONS), same convention as `query_memory`
    above -- Qdrant point IDs are only unique within a collection, not globally."""
    if collection not in COLLECTIONS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown collection '{collection}'. Valid collections: {COLLECTIONS}",
        )
    _qdrant_client().delete(collection_name=collection, points_selector=[vector_id])
    return DeleteVectorResponse(deleted=True, vector_id=vector_id, collection=collection)
