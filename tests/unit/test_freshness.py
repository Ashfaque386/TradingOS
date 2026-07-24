from datetime import date

import polars as pl
import pytest

from src.data.datalake.freshness import (
    DataFreshnessError,
    check_freshness,
    previous_trading_day,
    require_fresh,
)
from src.data.datalake.query import DataLake
from src.data.ingest.writer import ParquetLakeWriter


def test_previous_trading_day_skips_weekend():
    # 2024-01-01 is a Monday -> previous trading day is Friday 2023-12-29
    assert previous_trading_day(date(2024, 1, 1)) == date(2023, 12, 29)


def test_previous_trading_day_simple_weekday():
    assert previous_trading_day(date(2024, 1, 4)) == date(2024, 1, 3)


def _seed(tmp_path, symbol: str, last_date: date) -> DataLake:
    writer = ParquetLakeWriter(tmp_path)
    writer.write(
        pl.DataFrame(
            {
                "symbol": [symbol],
                "date": [last_date],
                "open": [100.0],
                "high": [101.0],
                "low": [99.0],
                "close": [100.5],
                "volume": [1000],
            }
        )
    )
    return DataLake(tmp_path)


def test_check_freshness_true_when_data_current(tmp_path):
    lake = _seed(tmp_path, "RELIANCE", date(2024, 1, 3))
    result = check_freshness(lake, "RELIANCE", as_of=date(2024, 1, 4))
    assert result.is_fresh is True


def test_check_freshness_false_when_data_stale(tmp_path):
    lake = _seed(tmp_path, "RELIANCE", date(2023, 12, 20))
    result = check_freshness(lake, "RELIANCE", as_of=date(2024, 1, 4))
    assert result.is_fresh is False


def test_require_fresh_raises_on_stale_symbol(tmp_path):
    lake = _seed(tmp_path, "RELIANCE", date(2023, 12, 20))
    with pytest.raises(DataFreshnessError):
        require_fresh(lake, ["RELIANCE"], as_of=date(2024, 1, 4))


def test_require_fresh_passes_when_all_symbols_current(tmp_path):
    writer = ParquetLakeWriter(tmp_path)
    for symbol in ["RELIANCE", "TCS"]:
        writer.write(
            pl.DataFrame(
                {
                    "symbol": [symbol],
                    "date": [date(2024, 1, 3)],
                    "open": [100.0],
                    "high": [101.0],
                    "low": [99.0],
                    "close": [100.5],
                    "volume": [1000],
                }
            )
        )
    lake = DataLake(tmp_path)
    require_fresh(lake, ["RELIANCE", "TCS"], as_of=date(2024, 1, 4))  # should not raise
