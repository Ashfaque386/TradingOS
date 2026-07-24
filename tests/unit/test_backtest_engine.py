import pandas as pd

from src.engine.backtest.engine import run_backtest


def _close_series() -> pd.Series:
    dates = pd.date_range("2024-01-01", periods=10, freq="D")
    prices = [100, 102, 101, 105, 110, 108, 103, 107, 112, 115]
    return pd.Series(prices, index=dates, name="close")


def test_run_backtest_produces_a_portfolio():
    close = _close_series()
    entries = pd.Series(
        [True, False, False, False, False, False, False, False, False, False], index=close.index
    )
    exits = pd.Series(
        [False, False, False, False, True, False, False, False, False, False], index=close.index
    )

    portfolio = run_backtest(close, entries, exits, init_cash=100_000.0)

    assert portfolio.init_cash == 100_000.0
    assert portfolio.total_return() != 0


def test_run_backtest_applies_flat_fees_and_slippage():
    close = _close_series()
    entries = pd.Series([True] + [False] * 9, index=close.index)
    exits = pd.Series([False] * 9 + [True], index=close.index)

    no_cost = run_backtest(close, entries, exits, fees=0.0, slippage=0.0)
    with_cost = run_backtest(close, entries, exits, fees=0.01, slippage=0.01)

    assert with_cost.final_value() < no_cost.final_value()


def test_run_backtest_with_no_signals_stays_in_cash():
    close = _close_series()
    entries = pd.Series([False] * 10, index=close.index)
    exits = pd.Series([False] * 10, index=close.index)

    portfolio = run_backtest(close, entries, exits, init_cash=50_000.0)

    assert portfolio.final_value() == 50_000.0
