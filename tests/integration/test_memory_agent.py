"""Integration tests for Memory Agent v1 (AGT-009) against real Qdrant."""

from unittest.mock import MagicMock, patch

from qdrant_client import QdrantClient

from src.agents.nodes.memory_agent import (
    archive_low_confidence_memories,
    generate_lessons_learned_summary,
)
from src.core.config import get_settings
from src.memory.collections import bootstrap_collections
from src.memory.strategy_memory import ingest_strategy_outcome


def test_archive_low_confidence_memories_marks_weak_strategies():
    client = QdrantClient(url=get_settings().qdrant_url)
    bootstrap_collections(client)

    weak_id = ingest_strategy_outcome(
        strategy_id="strat-weak",
        strategy_version_id="v1",
        hypothesis="Weak strategy",
        code="def run_backtest(data, config): return {}",
        asset_class="Equity",
        sharpe_ratio=0.1,
        max_drawdown=30.0,
        status="deprecated",
    )
    strong_id = ingest_strategy_outcome(
        strategy_id="strat-strong",
        strategy_version_id="v1",
        hypothesis="Strong strategy",
        code="def run_backtest(data, config): return {}",
        asset_class="Equity",
        sharpe_ratio=1.8,
        max_drawdown=5.0,
        status="active",
    )

    try:
        archived = archive_low_confidence_memories("trading_strategies", sharpe_threshold=0.5)
        assert weak_id in archived
        assert strong_id not in archived

        weak_point = client.retrieve(collection_name="trading_strategies", ids=[weak_id])[0]
        strong_point = client.retrieve(collection_name="trading_strategies", ids=[strong_id])[0]
        assert weak_point.payload["status"] == "archived"
        assert strong_point.payload["status"] == "active"
    finally:
        client.delete(collection_name="trading_strategies", points_selector=[weak_id, strong_id])


def _fake_response(content: str) -> MagicMock:
    response = MagicMock()
    response.choices[0].message.content = content
    return response


def test_generate_lessons_learned_summary_uses_real_stored_payloads():
    client = QdrantClient(url=get_settings().qdrant_url)
    bootstrap_collections(client)

    point_id = ingest_strategy_outcome(
        strategy_id="strat-summary-test",
        strategy_version_id="v1",
        hypothesis="Test strategy for summary generation",
        code="def run_backtest(data, config): return {}",
        asset_class="Equity",
        sharpe_ratio=0.3,
        max_drawdown=20.0,
        status="deprecated",
        failure_reason="Test seed",
    )

    try:
        with patch(
            "src.agents.nodes.memory_agent.complete",
            return_value=_fake_response("Lessons learned: avoid low-Sharpe mean reversion."),
        ) as mock_complete:
            summary = generate_lessons_learned_summary("trading_strategies")

        assert "Lessons learned" in summary
        sent_messages = mock_complete.call_args.kwargs["messages"]
        assert "strat-summary-test" in sent_messages[1]["content"]
    finally:
        client.delete(collection_name="trading_strategies", points_selector=[point_id])
