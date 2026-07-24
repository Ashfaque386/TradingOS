"""Backtest metrics suite tests (Phase 3 Epic E3.2 exit criterion) + the NFR-01 performance
benchmark (SRS §NFR-01: "Backtesting a single strategy across 5 years of daily OHLCV data must
complete in under 5 seconds utilizing VectorBT")."""

import time

import numpy as np
import pandas as pd
import pytest

from src.engine.backtest.engine import run_backtest
from src.engine.backtest.metrics import compute_metrics


def _close_series(n: int = 10) -> pd.Series:
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    prices = [100, 102, 101, 105, 110, 108, 103, 107, 112, 115][:n]
    return pd.Series(prices, index=dates, name="close")


def test_metrics_populated_for_a_profitable_multi_trade_portfolio():
    close = _close_series()
    entries = pd.Series(
        [True, False, False, False, False, True, False, False, False, False], index=close.index
    )
    exits = pd.Series(
        [False, False, False, False, True, False, False, False, False, True], index=close.index
    )

    portfolio = run_backtest(close, entries, exits, init_cash=100_000.0)
    metrics = compute_metrics(portfolio)

    assert metrics.total_trades == 2
    assert metrics.win_rate == 1.0  # both entries bought a rising leg
    assert metrics.max_drawdown >= 0.0  # stored as a positive magnitude, never negative
    assert metrics.cagr is not None
    # Zero losing trades -> gross_loss=0 -> profit_factor is infinite -> surfaced as None
    # (see _none_if_non_finite in src/engine/backtest/metrics.py), not as a numeric value.
    assert metrics.profit_factor is None
    assert metrics.expectancy is not None and metrics.expectancy > 0


def test_metrics_handles_zero_trades_without_nan():
    close = _close_series()
    entries = pd.Series([False] * 10, index=close.index)
    exits = pd.Series([False] * 10, index=close.index)

    portfolio = run_backtest(close, entries, exits)
    metrics = compute_metrics(portfolio)

    assert metrics.total_trades == 0
    assert metrics.sharpe_ratio == 0.0
    assert metrics.max_drawdown == 0.0
    # No closed trades -> these are undefined (NaN in vectorbt); must surface as None, not NaN.
    assert metrics.win_rate is None
    assert metrics.profit_factor is None
    assert metrics.expectancy is None


def test_win_rate_and_profit_factor_on_one_win_one_loss():
    # Manually verifiable: buy@100 sell@110 (win, +10%), buy@110 sell@99 (loss, -10%).
    # `from_signals` defaults to all-in position sizing, so each trade's notional is the
    # entire cash balance at that point (not a fixed size): trade 1 buys 1000 shares @100
    # (=100,000 cash) and sells @110 for a gross profit of 10,000; trade 2 then buys 1000
    # shares @110 (=110,000 cash, the now-larger balance) and sells @99 for a gross loss of
    # 11,000. profit_factor = gross_profit / gross_loss = 10,000 / 11,000 = 10/11.
    dates = pd.date_range("2024-01-01", periods=4, freq="D")
    close = pd.Series([100.0, 110.0, 110.0, 99.0], index=dates)
    entries = pd.Series([True, False, True, False], index=dates)
    exits = pd.Series([False, True, False, True], index=dates)

    portfolio = run_backtest(close, entries, exits, fees=0.0, slippage=0.0)
    metrics = compute_metrics(portfolio)

    assert metrics.total_trades == 2
    assert metrics.win_rate == pytest.approx(0.5)
    assert metrics.profit_factor == pytest.approx(10 / 11, rel=1e-6)


def test_nfr01_five_year_daily_backtest_completes_under_5_seconds():
    rng = np.random.default_rng(seed=42)
    dates = pd.date_range("2020-01-01", periods=5 * 252, freq="D")  # 5 trading years, daily
    close = pd.Series(100 + np.cumsum(rng.normal(0, 1, len(dates))), index=dates).clip(lower=1.0)

    fast_ma = close.rolling(20).mean()
    slow_ma = close.rolling(50).mean()
    entries = (fast_ma > slow_ma) & (fast_ma.shift(1) <= slow_ma.shift(1))
    exits = (fast_ma < slow_ma) & (fast_ma.shift(1) >= slow_ma.shift(1))

    start = time.perf_counter()
    portfolio = run_backtest(close, entries, exits, fees=0.001, slippage=0.0005)
    metrics = compute_metrics(portfolio)
    elapsed = time.perf_counter() - start

    assert elapsed < 5.0, f"NFR-01 violated: 5yr daily backtest took {elapsed:.2f}s (limit 5s)"
    assert metrics.total_trades >= 0
