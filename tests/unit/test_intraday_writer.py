"""REL-010 E10.7: real Parquet writes (to a real temp filesystem, no mocking of Parquet I/O
itself), matching tests/unit/test_writer.py's own convention for ParquetLakeWriter."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from src.data.ingest.intraday_writer import IntradayParquetWriter

_TZ = ZoneInfo("Asia/Kolkata")


def _rows(symbol: str, timestamps: list[datetime], closes: list[float]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": [symbol] * len(timestamps),
            "timestamp": timestamps,
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [100] * len(timestamps),
        }
    )


def test_write_creates_a_real_partitioned_parquet_file(tmp_path: Path):
    writer = IntradayParquetWriter(tmp_path)
    rows = _rows(
        "RELIANCE",
        [datetime(2024, 1, 2, 9, 15, tzinfo=_TZ), datetime(2024, 1, 2, 9, 16, tzinfo=_TZ)],
        [100.0, 101.0],
    )

    written = writer.write(rows)

    assert written == 2
    expected_path = tmp_path / "2024" / "01" / "02" / "RELIANCE.parquet"
    assert expected_path.exists()
    on_disk = pl.read_parquet(expected_path)
    assert on_disk.height == 2
    assert on_disk["close"].to_list() == [100.0, 101.0]


def test_write_is_idempotent_on_symbol_and_timestamp(tmp_path: Path):
    writer = IntradayParquetWriter(tmp_path)
    timestamps = [datetime(2024, 1, 2, 9, 15, tzinfo=_TZ)]

    writer.write(_rows("RELIANCE", timestamps, [100.0]))
    written_second_time = writer.write(_rows("RELIANCE", timestamps, [100.0]))

    assert written_second_time == 1  # same (symbol, timestamp) merges, not duplicates
    on_disk = pl.read_parquet(tmp_path / "2024" / "01" / "02" / "RELIANCE.parquet")
    assert on_disk.height == 1


def test_write_empty_dataframe_is_a_real_no_op(tmp_path: Path):
    writer = IntradayParquetWriter(tmp_path)
    empty = pl.DataFrame(
        schema={
            "symbol": pl.Utf8,
            "timestamp": pl.Datetime,
            "open": pl.Float64,
            "high": pl.Float64,
            "low": pl.Float64,
            "close": pl.Float64,
            "volume": pl.Int64,
        }
    )
    assert writer.write(empty) == 0
    assert list(tmp_path.iterdir()) == []
