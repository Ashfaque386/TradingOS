"""End-to-end backtest against the real year of RELIANCE EOD data ingested in Phase 1."""

from datetime import date

from src.core.config import get_settings
from src.data.datalake.query import DataLake
from src.engine.backtest.data_feed import load_close_series
from src.engine.backtest.engine import run_backtest


def test_backtest_runs_against_real_reliance_data():
    lake = DataLake(get_settings().data_lake_root / "ohlcv_daily")
    close = load_close_series(lake, "RELIANCE", end=date(2024, 7, 19), enforce_freshness=False)

    assert len(close) > 200  # a full year of real trading days

    fast_ma = close.rolling(20).mean()
    slow_ma = close.rolling(50).mean()
    entries = (fast_ma > slow_ma) & (fast_ma.shift(1) <= slow_ma.shift(1))
    exits = (fast_ma < slow_ma) & (fast_ma.shift(1) >= slow_ma.shift(1))

    portfolio = run_backtest(
        close, entries, exits, init_cash=100_000.0, fees=0.001, slippage=0.0005
    )

    stats = portfolio.stats()
    assert stats["Total Trades"] >= 0
    assert portfolio.final_value() > 0
