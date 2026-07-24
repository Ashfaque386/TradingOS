"""Data feed adapter: DuckDB/Parquet DataLake (Phase 1) -> pandas Series for VectorBT (Phase 3
Epic E3.2). VectorBT is pandas-native, while the rest of TradingOS is Polars-first, so this is
the one conversion boundary.
"""

from datetime import date, timedelta

import pandas as pd

from src.data.datalake.freshness import require_fresh
from src.data.datalake.query import DataLake


def load_close_series(
    lake: DataLake,
    symbol: str,
    start: date | None = None,
    end: date | None = None,
    *,
    enforce_freshness: bool = True,
) -> pd.Series:
    """Loads the close-price series for `symbol` as a pandas Series indexed by date, ready for
    vectorbt.Portfolio.from_signals(). Re-enforces the Data Freshness business rule (Rule 4,
    Phase 1) at this new engine's entrypoint, per Phase 3 exit criteria: a backtest cannot run
    if the lake is missing data through the requested `end` date."""
    if enforce_freshness:
        reference_date = (end or date.today()) + timedelta(days=1)
        require_fresh(lake, [symbol], as_of=reference_date)

    df = lake.read_symbol(symbol, start=start, end=end)
    if df.height == 0:
        raise ValueError(f"no data available for symbol {symbol!r} in the requested range")

    pandas_df = df.to_pandas().set_index("date").sort_index()
    return pandas_df["close"]


def load_ohlcv_frame(
    lake: DataLake,
    symbol: str,
    start: date | None = None,
    end: date | None = None,
    *,
    enforce_freshness: bool = True,
) -> pd.DataFrame:
    """Like load_close_series, but returns the full OHLCV frame (needed for ATR-based slippage
    modeling, Phase 3 Epic E3.2)."""
    if enforce_freshness:
        reference_date = (end or date.today()) + timedelta(days=1)
        require_fresh(lake, [symbol], as_of=reference_date)

    df = lake.read_symbol(symbol, start=start, end=end)
    if df.height == 0:
        raise ValueError(f"no data available for symbol {symbol!r} in the requested range")

    return df.to_pandas().set_index("date").sort_index()
