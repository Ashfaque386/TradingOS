"""DuckDB catalog views over the partitioned Parquet data lake (DB-022).

Real gap this closes: `DataLake`/`IntradayDataLake` (query.py) already encode the exact glob
patterns and column contracts a catalog would need, but every call re-issues a fresh ad hoc
`read_parquet(...)` query against a brand-new in-memory `duckdb.connect()` -- no view definition
persists between calls, and nothing outside this one Python class (a BI tool, the `duckdb` CLI,
another service) can query the lake without going through it. This module opens/creates a
persistent DuckDB file with named views wired to those same globs, so `SELECT * FROM ohlcv_daily
WHERE symbol='...'` works directly against that file with any DuckDB client.

Purely additive: does not touch `DataLake`/`IntradayDataLake`'s existing read path, which callers
keep using unchanged. Refreshed on a schedule (`src/agents/scheduler.py`, same cron-job pattern
already used for the data-lake backup job) so the views' underlying glob keeps matching new
partitions as they land -- `CREATE OR REPLACE VIEW` is idempotent, safe to re-run on every tick
even when no new partitions have appeared since the last run.
"""

from dataclasses import dataclass
from pathlib import Path

import duckdb

CATALOG_FILENAME = "catalog.duckdb"


@dataclass(frozen=True)
class CatalogRefreshResult:
    catalog_path: str
    views_created: list[str]


def refresh_catalog_views(data_lake_root: Path) -> CatalogRefreshResult:
    """Creates (or replaces) `ohlcv_daily` and `ohlcv_intraday` views in a persistent DuckDB file
    at `{data_lake_root}/catalog.duckdb`, over the exact same glob patterns
    `DataLake`/`IntradayDataLake` (query.py) already use. Real, idempotent, safe to call
    repeatedly -- `CREATE OR REPLACE VIEW` against a glob with zero matching files today still
    succeeds (DuckDB resolves the glob lazily, at query time, not at view-creation time), so this
    doesn't fail just because a given lake is empty or a symbol hasn't been ingested yet."""
    data_lake_root.mkdir(parents=True, exist_ok=True)
    catalog_path = data_lake_root / CATALOG_FILENAME
    daily_glob = str(data_lake_root / "ohlcv_daily" / "*" / "*" / "*.parquet")
    intraday_glob = str(data_lake_root / "ohlcv_intraday" / "*" / "*" / "*" / "*.parquet")

    # A CREATE VIEW's inner query is stored as SQL text and re-run fresh on every SELECT against
    # the view -- unlike a one-shot query.execute(sql, params) call, there is no later point at
    # which a bound `?` parameter could be re-supplied, so the glob must be inlined as a literal
    # here (not a security concern: data_lake_root is a Settings-configured Path, never
    # user-controlled input, and this is the same trust boundary DataLake.read_symbol's own
    # inline root already relies on).
    with duckdb.connect(str(catalog_path)) as conn:
        conn.execute(
            "CREATE OR REPLACE VIEW ohlcv_daily AS "
            f"SELECT * FROM read_parquet('{daily_glob}', hive_partitioning=false)"  # nosec B608
        )
        conn.execute(
            "CREATE OR REPLACE VIEW ohlcv_intraday AS "
            f"SELECT * FROM read_parquet('{intraday_glob}', hive_partitioning=false)"  # nosec B608
        )

    return CatalogRefreshResult(
        catalog_path=str(catalog_path),
        views_created=["ohlcv_daily", "ohlcv_intraday"],
    )
