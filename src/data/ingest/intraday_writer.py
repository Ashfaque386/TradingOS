"""Partitioned Parquet writer for intraday (minute-bar) data (REL-010 E10.7, DB-020).

Partitioned `root/{year}/{month}/{day}/{symbol}.parquet` -- finer-grained than the daily EOD
lake's year/month/symbol layout (src/data/ingest/writer.py), since a single real trading day's
minute bars for one symbol can already be ~375 rows (NSE's real 09:15-15:30 session); a whole
month in one file would grow unreasonably large for what's usually a single day's read. Same
idempotent-rerun guarantee as ParquetLakeWriter: de-duplicates on (symbol, timestamp).
"""

from pathlib import Path

import polars as pl

from src.data.ingest.intraday import INTRADAY_SCHEMA


class IntradayParquetWriter:
    def __init__(self, root: Path) -> None:
        self.root = root

    def write(self, rows: pl.DataFrame) -> int:
        if rows.height == 0:
            return 0

        missing = set(INTRADAY_SCHEMA) - set(rows.columns)
        if missing:
            raise ValueError(f"input rows missing required columns: {missing}")

        written = 0
        rows = rows.with_columns(
            pl.col("timestamp").dt.year().alias("_year"),
            pl.col("timestamp").dt.month().alias("_month"),
            pl.col("timestamp").dt.day().alias("_day"),
        )
        for (symbol, year, month, day), group in rows.group_by(
            ["symbol", "_year", "_month", "_day"]
        ):
            path = self._partition_path(str(symbol), int(year), int(month), int(day))
            merged = self._merge(path, group.drop(["_year", "_month", "_day"]))
            path.parent.mkdir(parents=True, exist_ok=True)
            merged.write_parquet(path)
            written += merged.height

        return written

    def _partition_path(self, symbol: str, year: int, month: int, day: int) -> Path:
        return self.root / str(year) / f"{month:02d}" / f"{day:02d}" / f"{symbol}.parquet"

    def _merge(self, path: Path, new_rows: pl.DataFrame) -> pl.DataFrame:
        if not path.exists():
            return new_rows.sort("timestamp")
        existing = pl.read_parquet(path)
        combined = pl.concat([existing, new_rows.select(existing.columns)])
        return combined.unique(subset=["symbol", "timestamp"], keep="last").sort("timestamp")
