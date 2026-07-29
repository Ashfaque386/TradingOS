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
        pattern = self._glob(symbol)
        query = f"SELECT * FROM read_parquet('{pattern}')"
        clauses = []
        if start is not None:
            clauses.append(f"date >= '{start.isoformat()}'")
        if end is not None:
            clauses.append(f"date <= '{end.isoformat()}'")
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY date"

        with duckdb.connect() as conn:
            try:
                return conn.execute(query).pl()
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
