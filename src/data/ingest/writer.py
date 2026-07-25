"""Writes long-format EOD rows into the Parquet data lake, partitioned year/month/symbol.

Idempotent by design: re-running ingestion for a date range that's already
present (e.g. a daily cron re-pulling today's bhavcopy) de-duplicates on
(symbol, date) rather than appending duplicate rows, so the same script is
safe to run repeatedly for updates.
"""

from pathlib import Path

import polars as pl

from src.data.ingest.base import EOD_SCHEMA


class ParquetLakeWriter:
    def __init__(self, root: Path) -> None:
        self.root = root

    def write(self, rows: pl.DataFrame) -> int:
        """Merges `rows` into the lake. Returns the number of new/updated rows written."""
        if rows.height == 0:
            return 0

        missing = set(EOD_SCHEMA) - set(rows.columns)
        if missing:
            raise ValueError(f"input rows missing required columns: {missing}")

        written = 0
        rows = rows.with_columns(
            pl.col("date").dt.year().alias("_year"),
            pl.col("date").dt.month().alias("_month"),
        )
        for (symbol, year, month), group in rows.group_by(["symbol", "_year", "_month"]):
            path = self._partition_path(str(symbol), int(year), int(month))
            merged = self._merge(path, group.drop(["_year", "_month"]))
            path.parent.mkdir(parents=True, exist_ok=True)
            merged.write_parquet(path)
            written += merged.height

        return written

    def _partition_path(self, symbol: str, year: int, month: int) -> Path:
        return self.root / str(year) / f"{month:02d}" / f"{symbol}.parquet"

    def _merge(self, path: Path, new_rows: pl.DataFrame) -> pl.DataFrame:
        if not path.exists():
            return new_rows.sort("date")
        existing = pl.read_parquet(path)
        combined = pl.concat([existing, new_rows.select(existing.columns)])
        return combined.unique(subset=["symbol", "date"], keep="last").sort("date")
