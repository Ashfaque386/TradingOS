from datetime import date
from unittest.mock import patch

import pandas as pd

from src.engine.optimization.optuna_strategy_adapter import sandboxed_code_to_strategy_factory
from src.engine.sandbox.backtest_runner import EntryExitPoint, RealBacktestOutcome


def _close_series() -> pd.Series:
    dates = pd.date_range("2025-01-01", periods=5)
    return pd.Series([100.0, 101.0, 99.0, 102.0, 103.0], index=dates)


def test_strategy_factory_passes_trial_params_into_config():
    close = _close_series()
    outcome = RealBacktestOutcome(passed=True, error=None, symbol_used="RELIANCE")

    with patch(
        "src.engine.optimization.optuna_strategy_adapter.run_real_backtest", return_value=outcome
    ) as mock_run:
        factory = sandboxed_code_to_strategy_factory(
            "def run_backtest(data, config):\n    return {}\n",
            universe=["RELIANCE"],
            date_from=date(2025, 1, 1),
            date_to=date(2025, 1, 5),
        )
        strategy_fn = factory({"sma_window": 20.0})
        strategy_fn(close)

    mock_run.assert_called_once()
    _, kwargs = mock_run.call_args
    assert kwargs["config"]["params"] == {"sma_window": 20.0}
    assert kwargs["universe"] == ["RELIANCE"]
    assert kwargs["date_from"] == date(2025, 1, 1)
    assert kwargs["date_to"] == date(2025, 1, 5)


def test_strategy_factory_extracts_real_entries_exits_reindexed_onto_close():
    close = _close_series()
    outcome = RealBacktestOutcome(
        passed=True,
        error=None,
        symbol_used="RELIANCE",
        entries_exits=[
            EntryExitPoint(date="2025-01-01", entry=True, exit=False),
            EntryExitPoint(date="2025-01-03", entry=False, exit=True),
        ],
    )

    with patch(
        "src.engine.optimization.optuna_strategy_adapter.run_real_backtest", return_value=outcome
    ):
        factory = sandboxed_code_to_strategy_factory(
            "def run_backtest(data, config):\n    return {}\n",
            universe=["RELIANCE"],
            date_from=date(2025, 1, 1),
            date_to=date(2025, 1, 5),
        )
        entries, exits = factory({"sma_window": 20.0})(close)

    assert list(entries.index) == list(close.index)
    assert entries.iloc[0] is True or bool(entries.iloc[0]) is True
    assert bool(exits.iloc[2]) is True
    assert bool(entries.iloc[1]) is False  # not a real entry date -- reindexed fill_value=False


def test_strategy_factory_returns_empty_signals_when_the_sandboxed_run_fails():
    """A parameter combination the generated code can't handle must not crash the sweep --
    matching optuna_sweep.py's own -inf-for-a-dead-region convention."""
    close = _close_series()
    outcome = RealBacktestOutcome(passed=False, error="boom", symbol_used="RELIANCE")

    with patch(
        "src.engine.optimization.optuna_strategy_adapter.run_real_backtest", return_value=outcome
    ):
        factory = sandboxed_code_to_strategy_factory(
            "def run_backtest(data, config):\n    return {}\n",
            universe=["RELIANCE"],
            date_from=date(2025, 1, 1),
            date_to=date(2025, 1, 5),
        )
        entries, exits = factory({"sma_window": 20.0})(close)

    assert not entries.any()
    assert not exits.any()
    assert list(entries.index) == list(close.index)
