"""REL-008 E8.1: the ML Feature Store (Phase_5_Machine_Learning_Architecture.md §1).

Offline/batch only -- Phase 5's "Online Store (Redis, sub-ms)" half has no live tick/WebSocket
data source to feed it (DB-020 OHLCV_INTRADAY has zero ingestion code anywhere in this codebase),
so it is deliberately not built here rather than built against a fabricated feed.

Built on the existing `DataLake`/`ParquetLakeWriter` conventions (src/data/datalake/query.py,
src/data/ingest/writer.py) rather than a new storage mechanism -- reads raw OHLCV via
`DataLake.read_symbol()`, writes engineered output back out as its own Parquet layer
(`<data_lake_root>/features/<version>/<symbol>.parquet`), read back the same DuckDB-glob way.

Real, pre-existing data-quality gap this module defends against: `HDFCBANK`'s ingested data has
14 real duplicate `(symbol, date)` rows with materially different OHLC values (e.g. two
2023-07-21 rows, one priced ~Rs650, one ~Rs1680) -- confirmed live against the running data lake.
This is not introduced by or in scope to fix here, but `build_feature_frame()` must refuse to
silently train on it.
"""

import hashlib
import io
from datetime import date
from pathlib import Path

import duckdb
import polars as pl

from src.data.datalake.query import DataLake
from src.data.features.indicators import macd, with_indicators

FEATURE_SET_VERSION = "fs_v1"

# Every engineered feature build_feature_frame() produces -- the canonical column list every
# training runner (lightgbm_runner.py, tft_runner.py) and serving path (onnx_runtime_service.py)
# uses to select model inputs, kept in one place so they can never silently drift apart.
FEATURE_COLUMNS = [
    "sma_20",
    "ema_20",
    "rsi_14",
    "atr_14",
    "bb_upper",
    "bb_mid",
    "bb_lower",
    "macd_line",
    "macd_signal",
    "macd_hist",
    "vwap_20",
]


def rolling_vwap(df: pl.DataFrame, window: int = 20) -> pl.Series:
    """A rolling dollar-volume-weighted price over `window` days -- an *approximation* of a real
    session VWAP, named honestly as such. No intraday tick data exists in this codebase to compute
    genuine session VWAP (that requires trade-by-trade or at least intraday-bar data); this is the
    best real signal obtainable from daily EOD bars alone."""
    dollar_volume = df["close"] * df["volume"]
    rolling_dollar_volume = dollar_volume.rolling_sum(window_size=window)
    rolling_volume = df["volume"].rolling_sum(window_size=window)
    return rolling_dollar_volume / rolling_volume


def build_feature_frame(symbol: str, start: date, end: date, *, lake_root: Path) -> pl.DataFrame:
    """Reads raw OHLCV for `symbol` via the existing DataLake, defensively rejects duplicate
    `(symbol, date)` rows (see module docstring), applies the full engineered feature set, and
    drops the warm-up rows where the longest rolling window isn't yet defined."""
    lake = DataLake(lake_root)
    raw = lake.read_symbol(symbol, start=start, end=end)
    if raw.height == 0:
        raise ValueError(f"no raw OHLCV data found for {symbol!r} in [{start}, {end}]")

    unique_dates = raw.select("date").n_unique()
    if raw.height != unique_dates:
        dupes = raw.group_by("date").len().filter(pl.col("len") > 1).sort("date")["date"].to_list()
        raise ValueError(
            f"{symbol!r} has {raw.height - unique_dates} duplicate-date row(s) in the raw data "
            f"lake (dates: {dupes}) -- refusing to silently train on corrupted/ambiguous data"
        )

    macd_line, macd_signal, macd_hist = macd(raw)
    engineered = with_indicators(raw).with_columns(
        macd_line.alias("macd_line"),
        macd_signal.alias("macd_signal"),
        macd_hist.alias("macd_hist"),
        rolling_vwap(raw, window=20).alias("vwap_20"),
    )

    # Longest warm-up window across every feature computed above (bollinger/sma/macd-slow-ema/
    # vwap all use a 20-26 day window) -- drop rows where any engineered column is still null.
    return engineered.filter(pl.all_horizontal(pl.col(c).is_not_null() for c in FEATURE_COLUMNS))


def compute_training_data_hash(df: pl.DataFrame) -> str:
    """SHA-256 over the frame's deterministic Parquet-serialized bytes -- feeds DB-017's
    `training_data_hash` column with a real, reproducible fingerprint of the exact training data
    (Phase_5 §3's lineage requirement), not a placeholder."""
    buffer = io.BytesIO()
    df.write_parquet(buffer)
    return hashlib.sha256(buffer.getvalue()).hexdigest()


def _feature_store_path(root: Path, symbol: str, version: str) -> Path:
    return root / "features" / version / f"{symbol}.parquet"


def write_feature_store(
    df: pl.DataFrame, root: Path, symbol: str, version: str = FEATURE_SET_VERSION
) -> Path:
    """Full-overwrite per (symbol, version) -- feature computation is a deterministic pure
    function of the raw lake, so idempotent overwrite is correct and simpler than
    ParquetLakeWriter's merge-append semantics (which exist to handle incremental raw ingestion,
    a concern this module doesn't have)."""
    path = _feature_store_path(root, symbol, version)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)
    return path


def read_feature_store(
    symbol: str,
    root: Path,
    version: str = FEATURE_SET_VERSION,
    start: date | None = None,
    end: date | None = None,
) -> pl.DataFrame:
    """Mirrors DataLake.read_symbol()'s exact shape (DuckDB glob read, ordered by date)."""
    path = _feature_store_path(root, symbol, version)
    query = f"SELECT * FROM read_parquet('{path.as_posix()}')"
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
            return pl.DataFrame()
