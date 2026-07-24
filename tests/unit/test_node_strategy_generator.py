from unittest.mock import MagicMock, patch

from src.agents.nodes.strategy_generator import strategy_generator_node
from src.agents.state import EvaluationVerdict, TradingOSGraphState


def _fake_response(content: str) -> MagicMock:
    response = MagicMock()
    response.choices[0].message.content = content
    return response


_VALID_STRATEGY_JSON = (
    '{"hypothesis": "Mean reversion", "asset_class": "Equity", "style": "Intraday", '
    '"universe": ["RELIANCE"], "entry_conditions": "RSI < 30", '
    '"exit_conditions": "RSI > 70", "stop_loss": "2%", "take_profit": "4%", '
    '"position_sizing": "1% risk", "confidence_score": 0.7}'
)


def test_strategy_generator_node_first_attempt_has_zero_rejections():
    with (
        patch(
            "src.agents.nodes.strategy_generator.complete",
            return_value=_fake_response(_VALID_STRATEGY_JSON),
        ),
        patch("src.agents.nodes.strategy_generator.get_skill_registry") as mock_registry,
    ):
        mock_registry.return_value.execute.return_value = []
        result = strategy_generator_node(TradingOSGraphState(thread_id="t1"))

    assert result["strategy_logic"].hypothesis == "Mean reversion"
    assert result["strategy_rejection_count"] == 0


def test_strategy_generator_node_increments_rejection_count_after_fail_verdict():
    state = TradingOSGraphState(
        thread_id="t1",
        evaluation_verdict=EvaluationVerdict(
            verdict="FAIL",
            failure_reasons=["Sharpe too low"],
            feedback_for_strategy_generator="Try a different sector",
        ),
        strategy_rejection_count=2,
    )
    with (
        patch(
            "src.agents.nodes.strategy_generator.complete",
            return_value=_fake_response(_VALID_STRATEGY_JSON),
        ),
        patch("src.agents.nodes.strategy_generator.get_skill_registry") as mock_registry,
    ):
        mock_registry.return_value.execute.return_value = []
        result = strategy_generator_node(state)

    assert result["strategy_rejection_count"] == 3


def test_strategy_generator_node_queries_rag_memory_before_generating():
    with (
        patch(
            "src.agents.nodes.strategy_generator.complete",
            return_value=_fake_response(_VALID_STRATEGY_JSON),
        ),
        patch("src.agents.nodes.strategy_generator.get_skill_registry") as mock_registry,
    ):
        mock_registry.return_value.execute.return_value = [{"payload": {"status": "failed"}}]
        strategy_generator_node(TradingOSGraphState(thread_id="t1"))

    mock_registry.return_value.execute.assert_called_once()
    assert mock_registry.return_value.execute.call_args.args[0] == "query_qdrant_strategy_memory"
