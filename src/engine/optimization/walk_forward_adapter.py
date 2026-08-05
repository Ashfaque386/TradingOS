"""REL-024: bridges the LLM-generated sandboxed strategy code's real return contract (PMPT-004
v3's `entries_exits`, REL-022) onto `walk_forward.py`'s `StrategyFn` shape
(`close: pd.Series -> (entries, exits)`), and picks the rolling window sizes this codebase's own
default backtest window (365 calendar days, `DEFAULT_BACKTEST_LOOKBACK_DAYS` in both
src/agents/nodes/backtesting.py and src/api/routers/strategies.py) can actually support.

Before this module existed, no adapter existed at all -- `src/agents/nodes/optimization.py`'s own
docstring documented this as "real, unscoped engineering work discovered during REL-005
implementation, parked as explicit follow-up work." This closes it by re-using the one real
entries/exits signal series REL-022 already captures for the strategy's full backtest period,
rather than re-executing the LLM's sandboxed code once per window (fragile, and ~60-90s per run).

Window sizing: Phase_6_Trading_Engine_Design.md's own illustrative example (train 3 years/test 1
year) assumes multi-year history this codebase's real default backtest window doesn't have --
365 days total, not 6+ years. Train=4 months/test=1 month/step=1 month fits comfortably inside
that real window (>=3 rolling windows with margin), preserving the same "in-sample
significantly longer than out-of-sample" ratio the Phase_6 example itself uses (there: 3:1;
here: 4:1) rather than inventing an unrelated ratio.
"""

from dataclasses import dataclass

import pandas as pd

from src.engine.optimization.walk_forward import (
    StrategyFn,
    WalkForwardWindow,
    generate_walk_forward_windows,
    run_walk_forward_optimization,
)

WALK_FORWARD_TRAIN_PERIOD = pd.DateOffset(months=4)
WALK_FORWARD_TEST_PERIOD = pd.DateOffset(months=1)
WALK_FORWARD_STEP_PERIOD = pd.DateOffset(months=1)


@dataclass(frozen=True)
class WalkForwardWindowSummary:
    """A dashboard/persistence-friendly summary of one `WalkForwardWindowResult` -- the full
    train/test `BacktestMetrics` pair is real but too large to duplicate wholesale into JSONB for
    every window; these are the fields Phase_6 §3's own pass/fail rule and the /backtests
    dashboard actually need."""

    train_start: str
    train_end: str
    test_start: str
    test_end: str
    train_expectancy: float | None
    test_expectancy: float | None
    test_sharpe_ratio: float | None
    test_total_trades: int | None
    out_of_sample_passed: bool


def entries_exits_to_strategy_fn(signals: list[tuple[str, bool, bool]]) -> StrategyFn:
    """`signals` is REL-022's real captured entries/exits for the strategy's full backtest
    period, as `(date, entry, exit)` triples. The returned `StrategyFn` reindexes that one real
    series onto whatever `close` slice `run_walk_forward_optimization` calls it with (a window's
    train slice, then its test slice) -- exactly the "reuse the one real signal series" adapter
    this module exists to provide, not a re-simulation."""
    dates = pd.to_datetime([date for date, _, _ in signals])
    entries_full = pd.Series([entry for _, entry, _ in signals], index=dates).sort_index()
    exits_full = pd.Series([exit_ for _, _, exit_ in signals], index=dates).sort_index()

    def strategy_fn(close: pd.Series) -> tuple[pd.Series, pd.Series]:
        entries = entries_full.reindex(close.index, fill_value=False)
        exits = exits_full.reindex(close.index, fill_value=False)
        return entries, exits

    return strategy_fn


def _build_close_series(close_curve: list[tuple[str, float]]) -> pd.Series:
    dates = pd.to_datetime([date for date, _ in close_curve])
    return pd.Series([close for _, close in close_curve], index=dates).sort_index()


def run_walk_forward_from_real_backtest(
    close_curve: list[tuple[str, float]],
    entries_exits: list[tuple[str, bool, bool]],
) -> list[WalkForwardWindowSummary]:
    """The real, live entry point: given REL-022's real per-backtest close prices and
    entries/exits signals, runs Walk-Forward Optimization and returns per-window summaries.

    Honestly empty (not fabricated) when there isn't enough real data for even one full rolling
    window -- a pre-v3-contract strategy (no entries_exits captured at all) or a backtest window
    shorter than `WALK_FORWARD_TRAIN_PERIOD + WALK_FORWARD_TEST_PERIOD`."""
    if not close_curve or not entries_exits:
        return []

    close = _build_close_series(close_curve)
    windows: list[WalkForwardWindow] = generate_walk_forward_windows(
        pd.DatetimeIndex(close.index),
        train_period=WALK_FORWARD_TRAIN_PERIOD,
        test_period=WALK_FORWARD_TEST_PERIOD,
        step_period=WALK_FORWARD_STEP_PERIOD,
    )
    if not windows:
        return []

    strategy_fn = entries_exits_to_strategy_fn(entries_exits)
    result = run_walk_forward_optimization(close, strategy_fn, windows)

    return [
        WalkForwardWindowSummary(
            train_start=str(r.window.train_start.date()),
            train_end=str(r.window.train_end.date()),
            test_start=str(r.window.test_start.date()),
            test_end=str(r.window.test_end.date()),
            train_expectancy=r.train_metrics.expectancy,
            test_expectancy=r.test_metrics.expectancy,
            test_sharpe_ratio=r.test_metrics.sharpe_ratio,
            test_total_trades=r.test_metrics.total_trades,
            out_of_sample_passed=r.out_of_sample_passed,
        )
        for r in result.window_results
    ]
