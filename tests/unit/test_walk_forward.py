"""Walk-Forward Optimization tests (Phase 3 Epic E3.3 exit criterion):
"Walk-Forward Optimization runs across 3+ rolling in-sample/out-of-sample windows and correctly
rejects a known regime-overfit strategy in test." (Phase_14_Master_Development_Roadmap.md)
"""

import numpy as np
import pandas as pd

from src.engine.optimization.walk_forward import (
    generate_walk_forward_windows,
    run_walk_forward_optimization,
)


def _buy_and_hold(close: pd.Series) -> tuple[pd.Series, pd.Series]:
    """A maximally naive strategy: buy the first bar, sell the last. Used to expose whether a
    window's regime was an uptrend (positive expectancy) or a downtrend (negative) -- exactly
    the kind of regime-overfit strategy Phase_6 §3 says WFO must reject."""
    entries = pd.Series(False, index=close.index)
    exits = pd.Series(False, index=close.index)
    entries.iloc[0] = True
    exits.iloc[-1] = True
    return entries, exits


def test_generate_walk_forward_windows_produces_3_plus_rolling_windows():
    train_period = pd.DateOffset(years=3)
    test_period = pd.DateOffset(years=1)
    step_period = pd.DateOffset(years=1)

    dates = pd.date_range("2015-01-01", "2023-12-31", freq="D")
    windows = generate_walk_forward_windows(
        dates, train_period=train_period, test_period=test_period, step_period=step_period
    )

    assert len(windows) >= 3
    for window in windows:
        assert window.train_start < window.train_end == window.test_start < window.test_end
        assert window.train_start + train_period == window.train_end
        assert window.test_start + test_period == window.test_end

    # Rolls forward by step_period between consecutive windows.
    assert windows[1].train_start == windows[0].train_start + step_period


def test_wfo_rejects_a_strategy_that_only_works_in_one_regime():
    # A 3-year bull run immediately followed by a 4-year bear market -- a buy-and-hold strategy
    # looks great in-sample (window 1 trains entirely on the bull run) and, because every
    # rolling test window falls inside the bear market, fails out-of-sample in all of them.
    # Exactly the "post-COVID bull run" overfit scenario named in the design doc.
    start = pd.Timestamp("2019-01-01")
    bull_bear_split = start + pd.DateOffset(years=3)
    data_end = start + pd.DateOffset(years=7)

    bull_dates = pd.date_range(start, bull_bear_split - pd.Timedelta(days=1), freq="D")
    bear_dates = pd.date_range(bull_bear_split, data_end - pd.Timedelta(days=1), freq="D")

    bull_close = pd.Series(np.linspace(100, 400, len(bull_dates)), index=bull_dates)
    bear_close = pd.Series(np.linspace(400, 100, len(bear_dates) + 1)[1:], index=bear_dates)
    close = pd.concat([bull_close, bear_close])

    windows = generate_walk_forward_windows(
        close.index,
        train_period=pd.DateOffset(years=3),
        test_period=pd.DateOffset(years=1),
        step_period=pd.DateOffset(years=1),
    )
    assert len(windows) >= 3
    # Every test window must fall inside the bear period for this scenario to be meaningful.
    assert all(w.test_start >= bull_bear_split for w in windows)

    result = run_walk_forward_optimization(close, _buy_and_hold, windows)

    assert result.passed is False
    assert all(not r.out_of_sample_passed for r in result.window_results)
    # Every test window's expectancy should be negative (bought high in the bull tail, sold
    # into the bear decline) -- not just "not positive", but a real, checkable failure.
    assert all(
        r.test_metrics.expectancy is not None and r.test_metrics.expectancy < 0
        for r in result.window_results
    )


def test_wfo_passes_a_strategy_that_is_robust_across_regimes():
    # A steady, uninterrupted uptrend across the whole span -- buy-and-hold should show
    # positive expectancy in every out-of-sample window, demonstrating WFO's pass path too.
    dates = pd.date_range("2015-01-01", "2023-12-31", freq="D")
    close = pd.Series(np.linspace(100, 1000, len(dates)), index=dates)

    windows = generate_walk_forward_windows(
        close.index,
        train_period=pd.DateOffset(years=3),
        test_period=pd.DateOffset(years=1),
        step_period=pd.DateOffset(years=1),
    )
    assert len(windows) >= 3

    result = run_walk_forward_optimization(close, _buy_and_hold, windows)

    assert result.passed is True
    assert all(r.out_of_sample_passed for r in result.window_results)
