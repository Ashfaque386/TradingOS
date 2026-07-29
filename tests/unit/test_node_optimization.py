from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.nodes.optimization import optimization_node
from src.agents.state import EquityCurvePoint, EvaluationVerdict, TradingOSGraphState


def _state(equity_curve=None, verdict="PASS"):
    equity_curve = equity_curve or [
        EquityCurvePoint(date="2024-01-01", equity=100_000.0),
        EquityCurvePoint(date="2024-01-02", equity=101_000.0),
        EquityCurvePoint(date="2024-01-03", equity=99_500.0),
    ]
    return TradingOSGraphState(
        thread_id="t1",
        equity_curve=equity_curve,
        evaluation_verdict=EvaluationVerdict(verdict=verdict),
    )


def test_optimization_node_requires_pass_verdict():
    with pytest.raises(ValueError):
        optimization_node(_state(verdict="FAIL"))


def test_optimization_node_skips_monte_carlo_with_insufficient_equity_data():
    single_point = [EquityCurvePoint(date="2024-01-01", equity=100_000.0)]
    result = optimization_node(_state(equity_curve=single_point))

    assert result["optimization_result"].passed is False
    assert "Insufficient equity curve data" in result["optimization_result"].notes
    assert "Walk-Forward" in result["optimization_result"].notes


def test_optimization_node_marks_robust_when_p95_within_tolerance():
    fake_result = SimpleNamespace(percentile_95_max_drawdown=0.15, historical_max_drawdown=0.12)
    with patch(
        "src.agents.nodes.optimization._run_monte_carlo", new_callable=AsyncMock
    ) as mock_run:
        mock_run.return_value = fake_result
        result = optimization_node(_state())

    opt = result["optimization_result"]
    assert opt.passed is True
    assert opt.robustness_score == 0.15
    assert "within" in opt.notes
    mock_run.assert_called_once()


def test_optimization_node_marks_not_robust_when_p95_exceeds_tolerance():
    fake_result = SimpleNamespace(percentile_95_max_drawdown=0.50, historical_max_drawdown=0.10)
    with patch(
        "src.agents.nodes.optimization._run_monte_carlo", new_callable=AsyncMock
    ) as mock_run:
        mock_run.return_value = fake_result
        result = optimization_node(_state())

    assert result["optimization_result"].passed is False
    assert "exceeds" in result["optimization_result"].notes
