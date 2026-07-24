from datetime import date

import polars as pl
import pytest

from src.data.datalake.freshness import DataFreshnessError
from src.data.datalake.query import DataLake
from src.data.ingest.writer import ParquetLakeWriter
from src.engine.backtest.data_feed import load_close_series, load_ohlcv_frame


def _seed(tmp_path, symbol: str, dates: list[date]) -> DataLake:
    writer = ParquetLakeWriter(tmp_path)
    writer.write(
        pl.DataFrame(
            {
                "symbol": [symbol] * len(dates),
                "date": dates,
                "open": [100.0 + i for i in range(len(dates))],
                "high": [101.0 + i for i in range(len(dates))],
                "low": [99.0 + i for i in range(len(dates))],
                "close": [100.5 + i for i in range(len(dates))],
                "volume": [1000] * len(dates),
            }
        )
    )
    return DataLake(tmp_path)


def test_load_close_series_returns_pandas_series_indexed_by_date(tmp_path):
    dates = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)]
    lake = _seed(tmp_path, "RELIANCE", dates)

    series = load_close_series(lake, "RELIANCE", end=date(2024, 1, 4), enforce_freshness=False)

    assert len(series) == 3
    assert series.index.name == "date"
    assert list(series.values) == [100.5, 101.5, 102.5]


def test_load_close_series_raises_on_missing_symbol(tmp_path):
    lake = DataLake(tmp_path)
    with pytest.raises(ValueError, match="no data available"):
        load_close_series(lake, "NONEXISTENT", enforce_freshness=False)


def test_load_close_series_enforces_freshness_by_default(tmp_path):
    dates = [date(2023, 1, 2), date(2023, 1, 3)]
    lake = _seed(tmp_path, "RELIANCE", dates)

    with pytest.raises(DataFreshnessError):
        load_close_series(lake, "RELIANCE", end=date(2024, 1, 4))


def test_load_close_series_can_skip_freshness_check(tmp_path):
    dates = [date(2023, 1, 2), date(2023, 1, 3)]
    lake = _seed(tmp_path, "RELIANCE", dates)

    series = load_close_series(lake, "RELIANCE", end=date(2024, 1, 4), enforce_freshness=False)
    assert len(series) == 2


def test_load_ohlcv_frame_has_expected_columns(tmp_path):
    dates = [date(2024, 1, 2), date(2024, 1, 3)]
    lake = _seed(tmp_path, "RELIANCE", dates)

    frame = load_ohlcv_frame(lake, "RELIANCE", end=date(2024, 1, 3), enforce_freshness=False)

    assert list(frame.columns) == ["symbol", "open", "high", "low", "close", "volume"]
    assert frame.index.name == "date"


def test_load_ohlcv_frame_enforces_freshness_by_default(tmp_path):
    # load_ohlcv_frame is the second real backtest entrypoint (used for ATR-based slippage
    # modeling, src/engine/backtest/friction.py) -- the Data Freshness business rule (Rule 4)
    # must be re-verified here too, not just on load_close_series.
    dates = [date(2023, 1, 2), date(2023, 1, 3)]
    lake = _seed(tmp_path, "RELIANCE", dates)

    with pytest.raises(DataFreshnessError):
        load_ohlcv_frame(lake, "RELIANCE", end=date(2024, 1, 4))
