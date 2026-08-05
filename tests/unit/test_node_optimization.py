from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest

from src.agents.nodes.optimization import optimization_node
from src.agents.state import (
    ClosePricePoint,
    EntryExitSignal,
    EquityCurvePoint,
    EvaluationVerdict,
    TradingOSGraphState,
)


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


def test_optimization_node_runs_real_walk_forward_when_state_has_entries_exits_and_close_curve():
    # REL-024: a trade opening every 10 business days and closing 5 days later, repeating for
    # ~8 months -- real, scattered entries/exits (not a single buy-and-hold pair), long enough
    # to span walk_forward_adapter.py's real WALK_FORWARD_TRAIN_PERIOD (4mo) + TEST_PERIOD (1mo).
    dates = pd.bdate_range("2025-01-01", periods=170)
    entries_exits = [
        EntryExitSignal(date=str(d.date()), entry=(i % 10 == 0), exit=(i % 10 == 5))
        for i, d in enumerate(dates)
    ]
    close_curve = [
        ClosePricePoint(date=str(d.date()), close=100.0 + (i % 20)) for i, d in enumerate(dates)
    ]
    state = TradingOSGraphState(
        thread_id="t1",
        equity_curve=_state().equity_curve,
        entries_exits=entries_exits,
        close_curve=close_curve,
        evaluation_verdict=EvaluationVerdict(verdict="PASS"),
    )

    fake_result = SimpleNamespace(percentile_95_max_drawdown=0.15, historical_max_drawdown=0.12)
    with patch(
        "src.agents.nodes.optimization._run_monte_carlo", new_callable=AsyncMock
    ) as mock_run:
        mock_run.return_value = fake_result
        result = optimization_node(state)

    opt = result["optimization_result"]
    assert opt.walk_forward_results != []
    assert opt.walk_forward_passed is not None
    assert "rolling out-of-sample windows" in opt.notes
    assert "skipped" not in opt.notes
    for window in opt.walk_forward_results:
        assert set(window) == {
            "train_start",
            "train_end",
            "test_start",
            "test_end",
            "train_expectancy",
            "test_expectancy",
            "test_sharpe_ratio",
            "test_total_trades",
            "out_of_sample_passed",
        }
