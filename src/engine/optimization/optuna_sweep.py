"""Optuna hyperparameter sweep (Phase 3 Epic E3.3), per Phase_4_AI_Agent_Design.md's
Optimization Agent (`run_optuna_sweep()` tool):

  "...design and execute a comprehensive optimization workflow that includes parameter
  sensitivity analysis, Optuna-based hyperparameter optimization... Define realistic parameter
  boundaries to prevent overfitting and avoid selecting solutions that rely on narrow or
  unstable parameter ranges."

This module owns the sweep mechanics (parameter space -> Optuna trials -> backtest metric);
the strategy itself is supplied by the caller as a `strategy_factory(params) -> StrategyFn` (see
src/engine/optimization/walk_forward.py's StrategyFn), so this stays strategy-agnostic, same
pattern as the WFO and Monte Carlo primitives before it. Parameter sensitivity is computed via
Optuna's own `get_param_importances` (fANOVA-based) rather than a hand-rolled heuristic --
that's a well-tested, standard technique Optuna already ships, not something to reinvent.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import optuna
import pandas as pd

from src.engine.backtest.engine import run_backtest
from src.engine.backtest.metrics import compute_metrics
from src.engine.optimization.walk_forward import StrategyFn

optuna.logging.set_verbosity(optuna.logging.WARNING)

ParamKind = Literal["int", "float"]
ParamSpace = dict[str, tuple[ParamKind, float, float]]
StrategyFactory = Callable[[dict[str, float]], StrategyFn]


@dataclass(frozen=True)
class OptunaTrialResult:
    params: dict[str, float]
    metric_value: float


@dataclass(frozen=True)
class OptunaSweepResult:
    best_params: dict[str, float]
    best_value: float
    trials: list[OptunaTrialResult]
    parameter_importances: dict[str, float]


def run_optuna_sweep(
    close: pd.Series,
    param_space: ParamSpace,
    strategy_factory: StrategyFactory,
    *,
    objective_metric: str = "sharpe_ratio",
    n_trials: int = 50,
    fees: float = 0.0,
    slippage: float = 0.0,
    seed: int | None = None,
) -> OptunaSweepResult:
    """Searches `param_space` (e.g. `{"fast_window": ("int", 5, 50), "slow_window": ("int", 20,
    200)}`) for the parameters that maximize `objective_metric` (any float field on
    `BacktestMetrics`) via `n_trials` Optuna-guided backtests. A trial whose metric is undefined
    (e.g. Sharpe/expectancy is `None` because the parameters produced zero closed trades) scores
    `-inf`, so Optuna steers away from parameter regions that don't actually trade rather than
    treating them as neutral."""
    sampler = optuna.samplers.TPESampler(seed=seed)
    study = optuna.create_study(direction="maximize", sampler=sampler)
    trial_results: list[OptunaTrialResult] = []

    def objective(trial: optuna.Trial) -> float:
        params: dict[str, float] = {}
        for name, (kind, low, high) in param_space.items():
            if kind == "int":
                params[name] = trial.suggest_int(name, int(low), int(high))
            else:
                params[name] = trial.suggest_float(name, low, high)

        strategy_fn = strategy_factory(params)
        entries, exits = strategy_fn(close)
        portfolio = run_backtest(close, entries, exits, fees=fees, slippage=slippage)
        metrics = compute_metrics(portfolio)
        raw_value: float | None = getattr(metrics, objective_metric)
        value: float = float("-inf") if raw_value is None else raw_value

        trial_results.append(OptunaTrialResult(params=params, metric_value=value))
        return value

    study.optimize(objective, n_trials=n_trials)

    try:
        parameter_importances = dict(optuna.importance.get_param_importances(study))
    except (RuntimeError, ValueError):
        # get_param_importances needs enough completed trials with varied, finite objective
        # values (fANOVA); with too few trials or a degenerate (all -inf) objective it raises
        # rather than returning a meaningless result -- surfaced here as "no signal yet"
        # instead of failing the whole sweep.
        parameter_importances = {}

    return OptunaSweepResult(
        best_params=study.best_params,
        best_value=study.best_value,
        trials=trial_results,
        parameter_importances=parameter_importances,
    )
