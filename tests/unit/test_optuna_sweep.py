"""Optuna hyperparameter sweep tests (Phase 3 Epic E3.3), per Phase_4_AI_Agent_Design.md's
Optimization Agent tool `run_optuna_sweep()`: parameter sensitivity analysis via Optuna-based
hyperparameter optimization.
"""

import numpy as np
import pandas as pd

from src.engine.optimization.optuna_sweep import run_optuna_sweep


def _ma_crossover_factory(params):
    fast_window = int(params["fast_window"])
    slow_window = int(params["slow_window"])

    def strategy_fn(close: pd.Series) -> tuple[pd.Series, pd.Series]:
        fast_ma = close.rolling(fast_window).mean()
        slow_ma = close.rolling(slow_window).mean()
        entries = (fast_ma > slow_ma) & (fast_ma.shift(1) <= slow_ma.shift(1))
        exits = (fast_ma < slow_ma) & (fast_ma.shift(1) >= slow_ma.shift(1))
        return entries.fillna(False), exits.fillna(False)

    return strategy_fn


def _noisy_uptrend_close(n: int = 500, seed: int = 0) -> pd.Series:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=n, freq="D")
    drift = np.linspace(0, 50, n)
    noise = np.cumsum(rng.normal(0, 1, n))
    return pd.Series(100 + drift + noise, index=dates).clip(lower=1.0)


def test_run_optuna_sweep_returns_valid_result_within_bounds():
    close = _noisy_uptrend_close()
    param_space = {
        "fast_window": ("int", 5, 20),
        "slow_window": ("int", 21, 60),
    }

    result = run_optuna_sweep(close, param_space, _ma_crossover_factory, n_trials=15, seed=42)

    assert len(result.trials) == 15
    assert set(result.best_params.keys()) == {"fast_window", "slow_window"}
    assert 5 <= result.best_params["fast_window"] <= 20
    assert 21 <= result.best_params["slow_window"] <= 60
    assert result.best_value == result.best_value  # not NaN
    assert result.best_value != float("-inf")  # a real uptrend should produce real trades
    assert isinstance(result.parameter_importances, dict)


def test_run_optuna_sweep_is_deterministic_given_a_seed():
    close = _noisy_uptrend_close()
    param_space = {
        "fast_window": ("int", 5, 20),
        "slow_window": ("int", 21, 60),
    }

    result_a = run_optuna_sweep(close, param_space, _ma_crossover_factory, n_trials=10, seed=7)
    result_b = run_optuna_sweep(close, param_space, _ma_crossover_factory, n_trials=10, seed=7)

    assert result_a.best_params == result_b.best_params
    assert result_a.best_value == result_b.best_value


def test_run_optuna_sweep_scores_a_dead_parameter_region_as_negative_infinity():
    # fast_window and slow_window are pinned to the same fixed value, so the two moving
    # averages are always identical -- the crossover condition never fires, every trial
    # produces zero trades, and BacktestMetrics.expectancy is undefined (None), which must
    # score as -inf rather than as a misleadingly "neutral" 0.0.
    close = _noisy_uptrend_close()
    param_space = {
        "fast_window": ("int", 10, 10),
        "slow_window": ("int", 10, 10),
    }

    result = run_optuna_sweep(
        close, param_space, _ma_crossover_factory, objective_metric="expectancy", n_trials=5
    )

    assert result.best_value == float("-inf")
    assert all(t.metric_value == float("-inf") for t in result.trials)
