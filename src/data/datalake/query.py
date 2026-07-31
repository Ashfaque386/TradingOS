from datetime import date
from pathlib import Path
from typing import cast

import duckdb
import polars as pl


class DataLake:
    """DuckDB-backed read interface over the partitioned Parquet EOD data lake."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _glob(self, symbol: str) -> str:
        return str(self.root / "*" / "*" / f"{symbol}.parquet")

    def read_symbol(
        self, symbol: str, start: date | None = None, end: date | None = None
    ) -> pl.DataFrame:
        # REL-009 E9.3: `symbol` can genuinely reach here from an authenticated HTTP request
        # body (e.g. POST /ml/models/train's `symbols` field) -- a real Bandit B608 finding, not
        # a false positive, even though today's callers are all trusted/privileged roles.
        # DuckDB's `?` placeholders work inside table-function arguments too, so the whole query
        # (including the read_parquet() path) is genuinely parameterized, not string-built.
        pattern = self._glob(symbol)
        query = "SELECT * FROM read_parquet(?)"
        params: list[object] = [pattern]
        clauses = []
        if start is not None:
            clauses.append("date >= ?")
            params.append(start)
        if end is not None:
            clauses.append("date <= ?")
            params.append(end)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY date"

        with duckdb.connect() as conn:
            try:
                return conn.execute(query, params).pl()
            except duckdb.IOException:
                # No matching partitions yet for this symbol.
                return pl.DataFrame(
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

    def latest_date(self, symbol: str) -> date | None:
        df = self.read_symbol(symbol)
        if df.height == 0:
            return None
        return cast(date, df.select(pl.col("date").max()).item())

    def list_symbols(self) -> list[str]:
        """Every symbol actually ingested into this data lake -- read directly off the real
        Parquet partition filenames (`<root>/<year>/<month>/<SYMBOL>.parquet`), not a
        configured/expected watchlist. REL-005 E5.6 uses this so the Scheduler's daily Data
        Freshness gate (Business Rule 4) checks against symbols that genuinely exist, rather
        than a fabricated universe."""
        if not self.root.exists():
            return []
        return sorted({p.stem for p in self.root.glob("*/*/*.parquet")})


class IntradayDataLake:
    """Read interface over the REL-010 E10.7 minute-bar lake
    (src/data/ingest/intraday_writer.py::IntradayParquetWriter), partitioned one level deeper
    than the daily EOD lake above (`<root>/<year>/<month>/<day>/<SYMBOL>.parquet`, not
    `<root>/<year>/<month>/<SYMBOL>.parquet`) -- a separate glob depth, not a `DataLake`
    subclass, since the two partition layouts aren't interchangeable."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def read_symbol(self, symbol: str, day: date | None = None) -> pl.DataFrame:
        pattern = str(self.root / "*" / "*" / "*" / f"{symbol}.parquet")
        query = "SELECT * FROM read_parquet(?)"
        params: list[object] = [pattern]
        if day is not None:
            query += " WHERE CAST(timestamp AS DATE) = ?"
            params.append(day)
        query += " ORDER BY timestamp"

        with duckdb.connect() as conn:
            try:
                return conn.execute(query, params).pl()
            except duckdb.IOException:
                # No matching partitions yet for this symbol.
                return pl.DataFrame(
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
