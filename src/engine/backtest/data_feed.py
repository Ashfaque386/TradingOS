"""Data feed adapter: DuckDB/Parquet DataLake (Phase 1) -> pandas Series for VectorBT (Phase 3
Epic E3.2). VectorBT is pandas-native, while the rest of TradingOS is Polars-first, so this is
the one conversion boundary.

REL-010 E10.7: `adjust_for_corporate_actions=True` by default -- prior to this release, no
split/dividend adjustment was ever applied, a real correctness gap (see
src/engine/backtest/corporate_actions_adjust.py's own docstring for the full explanation and
scope limits). Defaulted on, not opt-in, since an un-adjusted backtest is the wrong number by
default, not a valid alternative mode a caller would deliberately choose.
"""

from datetime import date, timedelta

import pandas as pd

from src.core.db import get_session
from src.data.datalake.freshness import require_fresh
from src.data.datalake.query import DataLake
from src.engine.backtest.corporate_actions_adjust import (
    adjust_ohlcv_for_corporate_actions,
    load_corporate_actions,
)


def _maybe_adjust(
    df: pd.DataFrame, symbol: str, adjust_for_corporate_actions: bool
) -> pd.DataFrame:
    if not adjust_for_corporate_actions:
        return df
    with get_session() as session:
        actions = load_corporate_actions(session, symbol)
    return adjust_ohlcv_for_corporate_actions(df, actions)


def load_close_series(
    lake: DataLake,
    symbol: str,
    start: date | None = None,
    end: date | None = None,
    *,
    enforce_freshness: bool = True,
    adjust_for_corporate_actions: bool = True,
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
    pandas_df = _maybe_adjust(pandas_df, symbol, adjust_for_corporate_actions)
    return pandas_df["close"]


def load_ohlcv_frame(
    lake: DataLake,
    symbol: str,
    start: date | None = None,
    end: date | None = None,
    *,
    enforce_freshness: bool = True,
    adjust_for_corporate_actions: bool = True,
) -> pd.DataFrame:
    """Like load_close_series, but returns the full OHLCV frame (needed for ATR-based slippage
    modeling, Phase 3 Epic E3.2)."""
    if enforce_freshness:
        reference_date = (end or date.today()) + timedelta(days=1)
        require_fresh(lake, [symbol], as_of=reference_date)

    df = lake.read_symbol(symbol, start=start, end=end)
    if df.height == 0:
        raise ValueError(f"no data available for symbol {symbol!r} in the requested range")

    pandas_df = df.to_pandas().set_index("date").sort_index()
    return _maybe_adjust(pandas_df, symbol, adjust_for_corporate_actions)
