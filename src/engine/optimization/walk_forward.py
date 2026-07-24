"""Walk-Forward Optimization (Phase 3 Epic E3.3), per Phase_6_Trading_Engine_Design.md §3:

  "The historical data is sliced into rolling in-sample (training) and out-of-sample (testing)
  windows. E.g., Train on 2019-2021, Test on 2022. Train on 2020-2022, Test on 2023. ...
  The strategy must maintain a positive expectancy across all out-of-sample windows. If it only
  works in a specific bull market (e.g., post-COVID crash), it is rejected."

This module owns window slicing and the pass/fail aggregation rule; the strategy itself is
supplied by the caller as a `strategy_fn(close) -> (entries, exits)` callable so this stays
strategy-agnostic (works for a hardcoded rule strategy today, and for an LLM-generated one via
the Strategy Factory later).
"""

from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd

from src.agents.state import BacktestMetrics
from src.engine.backtest.engine import run_backtest
from src.engine.backtest.metrics import compute_metrics

StrategyFn = Callable[[pd.Series], tuple[pd.Series, pd.Series]]


@dataclass(frozen=True)
class WalkForwardWindow:
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp


@dataclass(frozen=True)
class WalkForwardWindowResult:
    window: WalkForwardWindow
    train_metrics: BacktestMetrics
    test_metrics: BacktestMetrics

    @property
    def out_of_sample_passed(self) -> bool:
        """Positive expectancy on the out-of-sample slice, per Phase_6 §3. `None` (no closed
        trades in the window, i.e. undefined expectancy) does not count as a pass -- a strategy
        that never trades out-of-sample hasn't demonstrated anything."""
        return self.test_metrics.expectancy is not None and self.test_metrics.expectancy > 0


@dataclass(frozen=True)
class WalkForwardResult:
    window_results: list[WalkForwardWindowResult]

    @property
    def passed(self) -> bool:
        """All out-of-sample windows must show positive expectancy -- a single failing window
        (e.g. a strategy that only works in one historical regime) rejects the strategy."""
        return len(self.window_results) > 0 and all(
            r.out_of_sample_passed for r in self.window_results
        )


def generate_walk_forward_windows(
    index: pd.DatetimeIndex,
    *,
    train_period: pd.DateOffset,
    test_period: pd.DateOffset,
    step_period: pd.DateOffset | None = None,
) -> list[WalkForwardWindow]:
    """Slices `index` into rolling (train, test) windows, e.g. train_period=3 years,
    test_period=1 year, step_period=1 year reproduces the Phase_6 §3 example (train
    2019-2021/test 2022, train 2020-2022/test 2023, ...). `step_period` defaults to
    `test_period` so consecutive test windows are contiguous and non-overlapping."""
    step = step_period or test_period
    data_start, data_end = index.min(), index.max()

    windows = []
    train_start = data_start
    while True:
        train_end = train_start + train_period
        test_start = train_end
        test_end = test_start + test_period
        if test_end > data_end:
            break
        windows.append(WalkForwardWindow(train_start, train_end, test_start, test_end))
        train_start = train_start + step

    return windows


def run_walk_forward_optimization(
    close: pd.Series,
    strategy_fn: StrategyFn,
    windows: list[WalkForwardWindow],
    *,
    fees: float = 0.0,
    slippage: float = 0.0,
) -> WalkForwardResult:
    """Runs `strategy_fn` independently against each window's train and test slice of `close`
    and evaluates the Phase_6 §3 out-of-sample expectancy rule across all windows."""
    results = []
    for window in windows:
        train_close = close.loc[window.train_start : window.train_end]
        test_close = close.loc[window.test_start : window.test_end]

        train_metrics = _backtest_slice(train_close, strategy_fn, fees=fees, slippage=slippage)
        test_metrics = _backtest_slice(test_close, strategy_fn, fees=fees, slippage=slippage)

        results.append(WalkForwardWindowResult(window, train_metrics, test_metrics))

    return WalkForwardResult(results)


def _backtest_slice(
    close_slice: pd.Series, strategy_fn: StrategyFn, *, fees: float, slippage: float
) -> BacktestMetrics:
    entries, exits = strategy_fn(close_slice)
    portfolio = run_backtest(close_slice, entries, exits, fees=fees, slippage=slippage)
    return compute_metrics(portfolio)
