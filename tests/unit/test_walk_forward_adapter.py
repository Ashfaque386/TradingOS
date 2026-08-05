"""REL-024 unit tests: the entries_exits -> StrategyFn adapter and the real
run_walk_forward_from_real_backtest entry point, mirroring test_walk_forward.py's own
buy-and-hold-regime-change style but exercised through the real REL-022 signal-series shape
(date/entry/exit triples + date/close pairs) rather than a raw StrategyFn callable.
"""

import pandas as pd

from src.engine.optimization.walk_forward_adapter import (
    entries_exits_to_strategy_fn,
    run_walk_forward_from_real_backtest,
)


def test_entries_exits_to_strategy_fn_reindexes_onto_an_arbitrary_close_slice():
    signals = [
        ("2025-01-01", True, False),
        ("2025-01-02", False, False),
        ("2025-01-03", False, True),
        ("2025-01-04", False, False),
    ]
    strategy_fn = entries_exits_to_strategy_fn(signals)

    # A close slice covering only part of the real signal range, plus a date the real series
    # never had a signal for -- the adapter must reindex, not assume identical ranges (a train/
    # test window slice is exactly this: a subset of the full backtest period).
    close = pd.Series(
        [100.0, 101.0, 99.0],
        index=pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-05"]),
    )
    entries, exits = strategy_fn(close)

    assert list(entries) == [False, False, False]
    assert list(exits) == [False, True, False]
    assert list(entries.index) == list(close.index)


def test_run_walk_forward_from_real_backtest_is_empty_without_enough_real_data():
    assert run_walk_forward_from_real_backtest([], []) == []
    assert run_walk_forward_from_real_backtest([("2025-01-01", 100.0)], []) == []
    # A real backtest window (30 days) far shorter than WALK_FORWARD_TRAIN_PERIOD (4 months) --
    # generate_walk_forward_windows produces zero windows, honestly, not a fabricated one.
    short_dates = pd.bdate_range("2025-01-01", periods=20)
    close_curve = [(str(d.date()), 100.0 + i) for i, d in enumerate(short_dates)]
    entries_exits = [
        (str(d.date()), i == 0, i == len(short_dates) - 1) for i, d in enumerate(short_dates)
    ]
    assert run_walk_forward_from_real_backtest(close_curve, entries_exits) == []


def test_run_walk_forward_from_real_backtest_runs_real_windows_over_a_real_365_day_span():
    # A real ~365-day trading-day span (this codebase's own DEFAULT_BACKTEST_LOOKBACK_DAYS) with
    # an SMA(5)/SMA(20) crossover signal -- the same real signal-generation shape
    # tests/integration/test_strategies_api.py's own sandboxed strategy fixture uses -- so every
    # window's slice has real, scattered entries/exits to trade on, not a single buy-and-hold
    # pair that only fires in whichever window happens to contain the global first/last date.
    dates = pd.bdate_range("2025-08-06", "2026-08-05")
    midpoint = len(dates) // 2
    bull = [100.0 + i * 0.5 for i in range(midpoint)]
    bear = [bull[-1] - i * 0.5 for i in range(1, len(dates) - midpoint + 1)]
    close = pd.Series(bull + bear, index=dates)

    fast = close.rolling(5).mean()
    slow = close.rolling(20).mean()
    entries = (fast > slow) & (fast.shift(1) <= slow.shift(1))
    exits = (fast < slow) & (fast.shift(1) >= slow.shift(1))

    close_curve = [(str(d.date()), float(c)) for d, c in close.items()]
    entries_exits = [
        (str(d.date()), bool(en), bool(ex))
        for d, en, ex in zip(dates, entries.values, exits.values, strict=True)
    ]

    windows = run_walk_forward_from_real_backtest(close_curve, entries_exits)

    assert len(windows) >= 3
    for w in windows:
        assert w.train_start < w.train_end == w.test_start < w.test_end
        assert isinstance(w.out_of_sample_passed, bool)
    # Real windows whose entire test slice falls inside the monotonic bear half (the back third
    # of the span, well past every window's test_start once rolling has advanced that far) close
    # at most one losing trade each -- a real, checkable failure, not a fabricated one.
    bear_only_windows = [w for w in windows if w.test_start > str(dates[midpoint].date())]
    assert bear_only_windows  # the scenario is only meaningful if some windows are bear-only
    assert all(not w.out_of_sample_passed for w in bear_only_windows)
