from datetime import date

import polars as pl

from src.data.ingest.writer import ParquetLakeWriter


def _rows(symbol: str, dates: list[date], closes: list[float]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": [symbol] * len(dates),
            "date": dates,
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [1000] * len(dates),
        }
    )


def test_write_creates_partitioned_parquet_file(tmp_path):
    writer = ParquetLakeWriter(tmp_path)
    rows = _rows("RELIANCE", [date(2024, 1, 2), date(2024, 1, 3)], [100.0, 101.0])

    written = writer.write(rows)

    assert written == 2
    expected_path = tmp_path / "2024" / "01" / "RELIANCE.parquet"
    assert expected_path.exists()
    result = pl.read_parquet(expected_path)
    assert result.height == 2


def test_write_is_idempotent_on_rerun(tmp_path):
    writer = ParquetLakeWriter(tmp_path)
    rows = _rows("RELIANCE", [date(2024, 1, 2)], [100.0])

    writer.write(rows)
    writer.write(rows)  # simulate a daily re-run pulling the same day again

    result = pl.read_parquet(tmp_path / "2024" / "01" / "RELIANCE.parquet")
    assert result.height == 1


def test_write_updates_existing_row_on_revised_data(tmp_path):
    writer = ParquetLakeWriter(tmp_path)
    writer.write(_rows("RELIANCE", [date(2024, 1, 2)], [100.0]))
    writer.write(_rows("RELIANCE", [date(2024, 1, 2)], [105.0]))  # corrected bhavcopy re-pull

    result = pl.read_parquet(tmp_path / "2024" / "01" / "RELIANCE.parquet")
    assert result.height == 1
    assert result["close"][0] == 105.0


def test_write_appends_new_month_partition_separately(tmp_path):
    writer = ParquetLakeWriter(tmp_path)
    writer.write(_rows("RELIANCE", [date(2024, 1, 31)], [100.0]))
    writer.write(_rows("RELIANCE", [date(2024, 2, 1)], [101.0]))

    assert (tmp_path / "2024" / "01" / "RELIANCE.parquet").exists()
    assert (tmp_path / "2024" / "02" / "RELIANCE.parquet").exists()


def test_write_empty_dataframe_is_a_noop(tmp_path):
    writer = ParquetLakeWriter(tmp_path)
    empty = pl.DataFrame(
        schema={
            "symbol": pl.Utf8,
            "date": pl.Date,
            "open": pl.Float64,
            "high": pl.Float64,
            "low": pl.Float64,
            "close": pl.Float64,
            "volume": pl.Int64,
        }
    )
    assert writer.write(empty) == 0
