from unittest.mock import patch

import pytest

from src.agents.nodes.memory_ingest import memory_ingest_node
from src.agents.state import (
    BacktestMetrics,
    EvaluationVerdict,
    PythonCode,
    StrategyLogic,
    TradingOSGraphState,
)

_STRATEGY = StrategyLogic(
    hypothesis="Overfit RSI mean reversion",
    asset_class="Equity",
    style="Intraday",
    universe=["TCS"],
    entry_conditions="RSI < 30",
    exit_conditions="RSI > 70",
    stop_loss="2%",
    take_profit="4%",
    position_sizing="1% risk",
    confidence_score=0.5,
)
_CODE = PythonCode(code="def run_backtest(data, config):\n    return {}\n", version_no=2)
_METRICS = BacktestMetrics(sharpe_ratio=0.1, max_drawdown=0.28)
_FAIL_VERDICT = EvaluationVerdict(
    verdict="FAIL",
    failure_reasons=["Sharpe too low", "Overfit to a single regime"],
    feedback_for_strategy_generator="try a different universe",
)


def _state(**overrides) -> TradingOSGraphState:
    defaults = {
        "thread_id": "t1",
        "strategy_logic": _STRATEGY,
        "python_code": _CODE,
        "backtest_metrics": _METRICS,
        "evaluation_verdict": _FAIL_VERDICT,
    }
    defaults.update(overrides)
    return TradingOSGraphState(**defaults)


def test_memory_ingest_node_requires_strategy_logic():
    with pytest.raises(ValueError):
        memory_ingest_node(_state(strategy_logic=None))


def test_memory_ingest_node_requires_python_code():
    with pytest.raises(ValueError):
        memory_ingest_node(_state(python_code=None))


def test_memory_ingest_node_requires_backtest_metrics():
    with pytest.raises(ValueError):
        memory_ingest_node(_state(backtest_metrics=None))


def test_memory_ingest_node_requires_a_fail_verdict():
    with pytest.raises(ValueError):
        memory_ingest_node(_state(evaluation_verdict=EvaluationVerdict(verdict="PASS")))


def test_memory_ingest_node_calls_ingest_strategy_outcome_with_real_state_data():
    with patch("src.agents.nodes.memory_ingest.ingest_strategy_outcome") as mock_ingest:
        mock_ingest.return_value = "point-id-123"
        result = memory_ingest_node(_state())

    assert result == {}
    mock_ingest.assert_called_once_with(
        strategy_id="t1",
        strategy_version_id="t1-v2",
        hypothesis="Overfit RSI mean reversion",
        code="def run_backtest(data, config):\n    return {}\n",
        asset_class="Equity",
        sharpe_ratio=0.1,
        max_drawdown=0.28,
        status="deprecated",
        failure_reason="Sharpe too low; Overfit to a single regime",
    )


def test_memory_ingest_node_falls_back_to_thread_id_and_version_no_without_strategy_version_id():
    # strategy_version_id is only set by python_code_generator_node -- a state built without it
    # (e.g. constructed directly, not via the real graph) must still produce a real identifier.
    state = _state(strategy_version_id=None)
    with patch("src.agents.nodes.memory_ingest.ingest_strategy_outcome") as mock_ingest:
        mock_ingest.return_value = "point-id-456"
        memory_ingest_node(state)

    assert mock_ingest.call_args.kwargs["strategy_version_id"] == "t1-v2"
