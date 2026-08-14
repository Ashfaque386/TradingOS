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
    PythonCode,
    StrategyLogic,
    TradingOSGraphState,
)
from src.engine.optimization.optuna_sweep import OptunaSweepResult

_STRATEGY_WITH_TUNABLE_PARAMS = StrategyLogic(
    hypothesis="tunable momentum",
    asset_class="Equity",
    style="Swing",
    universe=["RELIANCE"],
    entry_conditions="close > sma_N",
    exit_conditions="close < sma_N",
    stop_loss="2%",
    take_profit="5%",
    position_sizing="fixed",
    confidence_score=0.7,
    tunable_parameters={"sma_window": ("int", 10, 50)},
)
_CODE = PythonCode(code="def run_backtest(data, config):\n    return {}\n", version_no=1)


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


def test_optimization_node_leaves_optuna_unrun_without_tunable_parameters():
    """REL-053: the common case for now -- no strategy_logic.tunable_parameters declared -- must
    stay honestly unrun, matching pre-REL-053 behavior exactly."""
    fake_result = SimpleNamespace(percentile_95_max_drawdown=0.15, historical_max_drawdown=0.12)
    with patch(
        "src.agents.nodes.optimization._run_monte_carlo", new_callable=AsyncMock
    ) as mock_run:
        mock_run.return_value = fake_result
        result = optimization_node(_state())

    opt = result["optimization_result"]
    assert opt.optuna_ran is False
    assert opt.optuna_best_value is None
    assert opt.optuna_parameter_importances == {}
    assert opt.best_params == {}
    assert "no structured tunable-parameter contract" in opt.notes


def test_optimization_node_leaves_optuna_unrun_without_real_prereqs_even_with_tunable_params():
    """tunable_parameters is declared, but close_curve/python_code aren't available yet -- a
    different, real reason, must not be conflated with "nothing was declared"."""
    state = TradingOSGraphState(
        thread_id="t1",
        equity_curve=_state().equity_curve,
        strategy_logic=_STRATEGY_WITH_TUNABLE_PARAMS,
        evaluation_verdict=EvaluationVerdict(verdict="PASS"),
    )
    fake_result = SimpleNamespace(percentile_95_max_drawdown=0.15, historical_max_drawdown=0.12)
    with patch(
        "src.agents.nodes.optimization._run_monte_carlo", new_callable=AsyncMock
    ) as mock_run:
        mock_run.return_value = fake_result
        result = optimization_node(state)

    opt = result["optimization_result"]
    assert opt.optuna_ran is False
    assert "tunable_parameters were declared" in opt.notes


def test_optimization_node_runs_real_optuna_wiring_when_tunable_parameters_declared():
    """REL-053: the real wiring path -- tunable_parameters + real close_curve/python_code must
    reach run_optuna_sweep() and the result must flow through into OptimizationResult."""
    close_curve = [
        ClosePricePoint(date=f"2025-01-{day:02d}", close=100.0 + day) for day in range(1, 11)
    ]
    state = TradingOSGraphState(
        thread_id="t1",
        equity_curve=_state().equity_curve,
        strategy_logic=_STRATEGY_WITH_TUNABLE_PARAMS,
        python_code=_CODE,
        close_curve=close_curve,
        evaluation_verdict=EvaluationVerdict(verdict="PASS"),
    )
    fake_optuna = OptunaSweepResult(
        best_params={"sma_window": 20.0},
        best_value=1.5,
        trials=[],
        parameter_importances={"sma_window": 1.0},
    )
    fake_mc = SimpleNamespace(percentile_95_max_drawdown=0.15, historical_max_drawdown=0.12)
    with (
        patch("src.agents.nodes.optimization._run_monte_carlo", new_callable=AsyncMock) as mock_mc,
        patch(
            "src.agents.nodes.optimization.run_optuna_sweep", return_value=fake_optuna
        ) as mock_optuna,
    ):
        mock_mc.return_value = fake_mc
        result = optimization_node(state)

    opt = result["optimization_result"]
    assert opt.optuna_ran is True
    assert opt.optuna_best_value == 1.5
    assert opt.best_params == {"sma_window": 20.0}
    assert opt.optuna_parameter_importances == {"sma_window": 1.0}
    assert "Optuna: 15 trials" in opt.notes
    mock_optuna.assert_called_once()
    _, kwargs = mock_optuna.call_args
    assert kwargs["n_trials"] == 15
