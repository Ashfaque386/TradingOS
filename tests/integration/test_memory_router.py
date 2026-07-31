"""REL-010 E10.8c: memory/RAG query API (src/api/routers/memory.py) against the real FastAPI
app + real Qdrant -- seeds a real point via the exact same `ingest_strategy_outcome` helper
already used by src/agents/tools/skills.py's QdrantStrategyMemorySkill, then queries it back
through the new HTTP surface.
"""

import uuid

from fastapi.testclient import TestClient
from qdrant_client import QdrantClient

from src.api.main import app
from src.core.config import get_settings
from src.memory.strategy_memory import ingest_strategy_outcome

client = TestClient(app)


def test_list_collections_reports_real_qdrant_state():
    response = client.get("/api/v1/memory/collections")
    assert response.status_code == 200
    body = response.json()
    names = {c["name"] for c in body}
    assert "trading_strategies" in names
    assert "news_sentiment" in names


def test_query_rejects_an_unknown_collection():
    response = client.get(
        "/api/v1/memory/query", params={"collection": "not-a-real-collection", "q": "test"}
    )
    assert response.status_code == 404


def test_query_finds_a_real_seeded_point_by_semantic_similarity():
    strategy_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())
    hypothesis = f"e10-8-memory-router-test-hypothesis-{uuid.uuid4().hex[:8]}"
    point_id = ingest_strategy_outcome(
        strategy_id=strategy_id,
        strategy_version_id=version_id,
        hypothesis=hypothesis,
        code="def generate_signals(data):\n    return data",
        asset_class="Equity",
        sharpe_ratio=1.5,
        max_drawdown=0.1,
        status="active",
    )
    try:
        response = client.get(
            "/api/v1/memory/query",
            params={"collection": "trading_strategies", "q": hypothesis, "top_k": 5},
        )
        assert response.status_code == 200
        hits = response.json()
        assert len(hits) > 0
        assert any(h["payload"]["strategy_id"] == strategy_id for h in hits)
        assert hits[0]["score"] > 0
    finally:
        client_qdrant = QdrantClient(url=get_settings().qdrant_url)
        client_qdrant.delete(
            collection_name="trading_strategies",
            points_selector=[point_id],
        )
