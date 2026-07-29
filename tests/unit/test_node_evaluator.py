from unittest.mock import MagicMock, patch

import pytest

from src.agents.nodes.evaluator import evaluator_node
from src.agents.state import BacktestMetrics, StrategyLogic, TradingOSGraphState

_STRATEGY = StrategyLogic(
    hypothesis="momentum",
    asset_class="Equity",
    style="Swing",
    universe=["RELIANCE"],
    entry_conditions="close > sma_20",
    exit_conditions="close < sma_20",
    stop_loss="2%",
    take_profit="5%",
    position_sizing="fixed",
    confidence_score=0.7,
)


def _fake_response(content: str) -> MagicMock:
    response = MagicMock()
    response.choices[0].message.content = content
    return response


def test_evaluator_node_requires_backtest_metrics():
    with pytest.raises(ValueError):
        evaluator_node(TradingOSGraphState(thread_id="t1"))


def test_evaluator_node_passes_above_sharpe_threshold_without_calling_llm():
    metrics = BacktestMetrics(sharpe_ratio=1.8, max_drawdown=-0.1)
    state = TradingOSGraphState(thread_id="t1", strategy_logic=_STRATEGY, backtest_metrics=metrics)

    with patch("src.agents.nodes.evaluator.complete") as mock_complete:
        result = evaluator_node(state)

    assert result["evaluation_verdict"].verdict == "PASS"
    assert result["evaluation_verdict"].failure_reasons == []
    mock_complete.assert_not_called()


def test_evaluator_node_fails_at_or_below_sharpe_threshold_and_calls_llm_for_feedback():
    metrics = BacktestMetrics(sharpe_ratio=1.2, max_drawdown=-0.3)
    state = TradingOSGraphState(thread_id="t1", strategy_logic=_STRATEGY, backtest_metrics=metrics)

    with patch(
        "src.agents.nodes.evaluator.complete",
        return_value=_fake_response('{"feedback": "Tighten entry filters."}'),
    ) as mock_complete:
        result = evaluator_node(state)

    verdict = result["evaluation_verdict"]
    assert verdict.verdict == "FAIL"
    assert "Sharpe Ratio 1.20" in verdict.failure_reasons[0]
    assert verdict.feedback_for_strategy_generator == "Tighten entry filters."
    assert mock_complete.call_args.args[0] == "research"


def test_evaluator_node_falls_back_to_deterministic_feedback_on_llm_failure():
    metrics = BacktestMetrics(sharpe_ratio=0.5, max_drawdown=-0.4)
    state = TradingOSGraphState(thread_id="t1", strategy_logic=_STRATEGY, backtest_metrics=metrics)

    with patch("src.agents.nodes.evaluator.complete", side_effect=RuntimeError("LLM down")):
        result = evaluator_node(state)

    verdict = result["evaluation_verdict"]
    assert verdict.verdict == "FAIL"
    assert "Backtest failed" in verdict.feedback_for_strategy_generator
