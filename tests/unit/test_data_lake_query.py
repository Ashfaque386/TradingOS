from datetime import date

import polars as pl

from src.data.datalake.query import DataLake
from src.data.ingest.writer import ParquetLakeWriter


def _write(tmp_path, symbol: str, on: date) -> None:
    ParquetLakeWriter(tmp_path).write(
        pl.DataFrame(
            {
                "symbol": [symbol],
                "date": [on],
                "open": [100.0],
                "high": [101.0],
                "low": [99.0],
                "close": [100.5],
                "volume": [1000],
            }
        )
    )


def test_list_symbols_returns_empty_for_nonexistent_root(tmp_path):
    lake = DataLake(tmp_path / "does_not_exist")
    assert lake.list_symbols() == []


def test_list_symbols_returns_empty_for_empty_lake(tmp_path):
    assert DataLake(tmp_path).list_symbols() == []


def test_list_symbols_returns_real_ingested_symbols_only(tmp_path):
    _write(tmp_path, "RELIANCE", date(2024, 1, 3))
    _write(tmp_path, "TCS", date(2024, 1, 3))

    assert DataLake(tmp_path).list_symbols() == ["RELIANCE", "TCS"]


def test_list_symbols_deduplicates_across_multiple_partitions(tmp_path):
    _write(tmp_path, "RELIANCE", date(2024, 1, 3))
    _write(tmp_path, "RELIANCE", date(2024, 2, 3))

    assert DataLake(tmp_path).list_symbols() == ["RELIANCE"]
