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
from src.core.security import ROLE_SYSTEM_ADMINISTRATOR
from src.memory.strategy_memory import ingest_strategy_outcome
from tests.auth_helpers import auth_header, cleanup_user, create_authenticated_user

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


# --- Ingest / delete (API-088/090, REL-062) -------------------------------------------------


def test_ingest_outcome_requires_the_gated_role():
    response = client.post(
        "/api/v1/memory/ingest",
        json={
            "strategy_id": str(uuid.uuid4()),
            "strategy_version_id": str(uuid.uuid4()),
            "hypothesis": "x",
            "code": "def generate_signals(data):\n    return data",
            "asset_class": "Equity",
            "sharpe_ratio": 1.0,
            "max_drawdown": 0.1,
            "status": "active",
        },
    )
    assert response.status_code == 401


def test_ingest_then_delete_a_real_outcome_round_trips_through_qdrant():
    admin_id, admin_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    headers = auth_header(admin_token)
    strategy_id = str(uuid.uuid4())
    hypothesis = f"e10-8-memory-router-ingest-test-{uuid.uuid4().hex[:8]}"
    point_id = None
    try:
        ingest_response = client.post(
            "/api/v1/memory/ingest",
            json={
                "strategy_id": strategy_id,
                "strategy_version_id": str(uuid.uuid4()),
                "hypothesis": hypothesis,
                "code": "def generate_signals(data):\n    return data",
                "asset_class": "Equity",
                "sharpe_ratio": 1.5,
                "max_drawdown": 0.1,
                "status": "active",
            },
            headers=headers,
        )
        assert ingest_response.status_code == 201
        point_id = ingest_response.json()["point_id"]

        query_response = client.get(
            "/api/v1/memory/query",
            params={"collection": "trading_strategies", "q": hypothesis, "top_k": 5},
        )
        assert any(h["payload"]["strategy_id"] == strategy_id for h in query_response.json())

        delete_response = client.delete(
            f"/api/v1/memory/{point_id}",
            params={"collection": "trading_strategies"},
            headers=headers,
        )
        assert delete_response.status_code == 200
        assert delete_response.json()["deleted"] is True

        query_after_response = client.get(
            "/api/v1/memory/query",
            params={"collection": "trading_strategies", "q": hypothesis, "top_k": 5},
        )
        assert not any(
            h["payload"]["strategy_id"] == strategy_id for h in query_after_response.json()
        )
        point_id = None  # already deleted -- nothing left for the finally block to clean up
    finally:
        if point_id is not None:
            QdrantClient(url=get_settings().qdrant_url).delete(
                collection_name="trading_strategies", points_selector=[point_id]
            )
        cleanup_user(admin_id)


def test_delete_vector_requires_the_gated_role():
    response = client.delete(
        f"/api/v1/memory/{uuid.uuid4()}", params={"collection": "trading_strategies"}
    )
    assert response.status_code == 401


def test_delete_vector_rejects_an_unknown_collection():
    admin_id, admin_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        response = client.delete(
            f"/api/v1/memory/{uuid.uuid4()}",
            params={"collection": "not-a-real-collection"},
            headers=auth_header(admin_token),
        )
        assert response.status_code == 404
    finally:
        cleanup_user(admin_id)
