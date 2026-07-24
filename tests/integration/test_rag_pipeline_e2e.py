"""End-to-end RAG pipeline checks (Phase 2 Epic E2.4 exit criteria):
- Qdrant retrieval p95 latency benchmark under a realistic collection size.
- A failed backtest's parameters are surfaced to (not silently dropped by) the next
  Strategy Generator ideation pass.
"""

import time
import uuid
from unittest.mock import MagicMock, patch

from qdrant_client import QdrantClient

from src.agents.nodes.strategy_generator import strategy_generator_node
from src.agents.state import TradingOSGraphState
from src.agents.tools.skills import QdrantStrategyMemorySkill
from src.core.config import get_settings
from src.memory.collections import bootstrap_collections
from src.memory.strategy_memory import ingest_strategy_outcome

# Generous budget for a local dev container running Ollama embeddings + Qdrant on the same
# host; this is not a production SLA, just a smoke check that retrieval isn't pathologically slow.
P95_LATENCY_BUDGET_SECONDS = 2.0
SEED_COUNT = 50


def test_qdrant_retrieval_p95_latency_under_budget():
    client = QdrantClient(url=get_settings().qdrant_url)
    bootstrap_collections(client)

    seeded_ids = [
        ingest_strategy_outcome(
            strategy_id=f"bench-{i}",
            strategy_version_id="v1",
            hypothesis=f"Benchmark strategy variant {i} on Nifty sector rotation",
            code="def run_backtest(data, config): return {}",
            asset_class="Equity",
            sharpe_ratio=1.0 + (i % 5) * 0.1,
            max_drawdown=10.0,
            status="active",
        )
        for i in range(SEED_COUNT)
    ]

    try:
        latencies = []
        for _ in range(10):
            start = time.perf_counter()
            QdrantStrategyMemorySkill().execute(query="Nifty sector rotation strategy", top_k=5)
            latencies.append(time.perf_counter() - start)

        latencies.sort()
        p95 = latencies[int(len(latencies) * 0.95) - 1]
        assert p95 < P95_LATENCY_BUDGET_SECONDS, (
            f"p95 retrieval latency {p95:.3f}s exceeded budget {P95_LATENCY_BUDGET_SECONDS}s "
            f"(all: {[round(x, 3) for x in latencies]})"
        )
    finally:
        client.delete(collection_name="trading_strategies", points_selector=seeded_ids)


def _fake_response(content: str) -> MagicMock:
    response = MagicMock()
    response.choices[0].message.content = content
    return response


def test_failed_strategy_is_surfaced_to_next_strategy_generator_pass():
    client = QdrantClient(url=get_settings().qdrant_url)
    bootstrap_collections(client)

    marker = f"unique-failure-marker-{uuid.uuid4().hex[:8]}"
    point_id = ingest_strategy_outcome(
        strategy_id=marker,
        strategy_version_id="v1",
        hypothesis="Overfitted RSI mean reversion on Bank Nifty, failed out-of-sample",
        code="def run_backtest(data, config): return {}",
        asset_class="Equity",
        sharpe_ratio=0.1,
        max_drawdown=28.0,
        status="deprecated",
        failure_reason="Overfit to a single volatility regime",
    )

    valid_strategy_json = (
        '{"hypothesis": "New idea", "asset_class": "Equity", "style": "Intraday", '
        '"universe": ["RELIANCE"], "entry_conditions": "x", "exit_conditions": "y", '
        '"stop_loss": "2%", "take_profit": "4%", "position_sizing": "1%", '
        '"confidence_score": 0.6}'
    )

    try:
        with patch(
            "src.agents.nodes.strategy_generator.complete",
            return_value=_fake_response(valid_strategy_json),
        ) as mock_complete:
            strategy_generator_node(TradingOSGraphState(thread_id="t1"))

        sent_messages = mock_complete.call_args.kwargs["messages"]
        user_content = sent_messages[1]["content"]
        assert marker in user_content, (
            "The failed strategy's identifying marker was not surfaced in the Strategy "
            "Generator's prompt -- RAG retrieval did not deprioritize/exclude it as intended."
        )
    finally:
        client.delete(collection_name="trading_strategies", points_selector=[point_id])
