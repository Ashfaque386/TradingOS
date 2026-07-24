"""Integration tests against real Qdrant + real Ollama embeddings."""

from qdrant_client import QdrantClient

from src.core.config import get_settings
from src.memory.collections import bootstrap_collections
from src.memory.strategy_memory import ingest_code_template, ingest_strategy_outcome


def test_ingest_strategy_outcome_is_retrievable():
    client = QdrantClient(url=get_settings().qdrant_url)
    bootstrap_collections(client)

    point_id = ingest_strategy_outcome(
        strategy_id="strat-1",
        strategy_version_id="v1",
        hypothesis="Overfitted mean reversion on Nifty Bank during 2020 bull run",
        code="def run_backtest(data, config): return {}",
        asset_class="Equity",
        sharpe_ratio=0.2,
        max_drawdown=25.0,
        status="deprecated",
        failure_reason="Overfitted to 2020 bull run",
    )

    try:
        point = client.retrieve(collection_name="trading_strategies", ids=[point_id])[0]
        assert point.payload["strategy_id"] == "strat-1"
        assert point.payload["failure_reason"] == "Overfitted to 2020 bull run"
        assert point.payload["status"] == "deprecated"
    finally:
        client.delete(collection_name="trading_strategies", points_selector=[point_id])


def test_ingest_code_template_is_retrievable():
    client = QdrantClient(url=get_settings().qdrant_url)
    bootstrap_collections(client)

    point_id = ingest_code_template(
        template_name="rsi_mean_reversion_v1",
        code="def run_backtest(data, config): return {}",
        strategy_pattern="RSI oversold mean reversion",
    )

    try:
        point = client.retrieve(collection_name="code_templates", ids=[point_id])[0]
        assert point.payload["template_name"] == "rsi_mean_reversion_v1"
    finally:
        client.delete(collection_name="code_templates", points_selector=[point_id])
