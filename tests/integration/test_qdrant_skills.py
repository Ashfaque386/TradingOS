"""Integration tests against the real Qdrant service (docker-compose `qdrant`) and the real
local Ollama embedding model (`nomic-embed-text` -- see src/memory/embeddings.py)."""

import uuid

from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

from src.agents.tools.skills import CodeTemplateSearchSkill, QdrantStrategyMemorySkill
from src.core.config import get_settings
from src.memory.collections import bootstrap_collections
from src.memory.embeddings import embed_text


def test_query_qdrant_strategy_memory_finds_seeded_point():
    client = QdrantClient(url=get_settings().qdrant_url)
    bootstrap_collections(client)

    text = "Mean reversion strategy on Nifty Bank using RSI oversold conditions"
    vector = embed_text(text)
    point_id = str(uuid.uuid4())
    client.upsert(
        collection_name="trading_strategies",
        points=[
            PointStruct(
                id=point_id,
                vector=vector,
                payload={"asset_class": "equity", "sharpe_ratio": 1.8, "status": "test-seed"},
            )
        ],
    )

    try:
        results = QdrantStrategyMemorySkill().execute(
            query="RSI mean reversion Bank Nifty", top_k=3
        )
        assert any(r["payload"].get("status") == "test-seed" for r in results)
    finally:
        client.delete(collection_name="trading_strategies", points_selector=[point_id])


def test_search_code_templates_finds_seeded_point():
    client = QdrantClient(url=get_settings().qdrant_url)
    bootstrap_collections(client)

    text = "VectorBT moving average crossover template"
    vector = embed_text(text)
    point_id = str(uuid.uuid4())
    client.upsert(
        collection_name="code_templates",
        points=[
            PointStruct(
                id=point_id,
                vector=vector,
                payload={"template_name": "ma_crossover_test_seed"},
            )
        ],
    )

    try:
        results = CodeTemplateSearchSkill().execute(query="moving average crossover", top_k=3)
        assert any(r["payload"].get("template_name") == "ma_crossover_test_seed" for r in results)
    finally:
        client.delete(collection_name="code_templates", points_selector=[point_id])
