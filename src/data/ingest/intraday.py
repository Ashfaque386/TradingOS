"""Intraday (minute-bar) ingestion (REL-010 E10.7, DB-020 OHLCV_INTRADAY -- previously zero
code anywhere in this codebase).

Real data source: Upstox's real historical-candle endpoint
(src/brokers/upstox_adapter.py::get_historical_candles) -- confirmed against Upstox's own
developer docs, not guessed. That method's own docstring records a real, confirmed limitation:
Upstox's SANDBOX returns a genuine 404 for this endpoint (empirically verified), so this
module's tests use a fake/mocked candle source rather than the real sandbox -- real live
verification needs a genuine production Upstox account, not configured in this dev environment
(an honest, stated gap, matching Kite Connect's own "no sandbox at all" precedent elsewhere in
this codebase).
"""

from datetime import date
from typing import Protocol

import polars as pl

INTRADAY_SCHEMA = ["symbol", "timestamp", "open", "high", "low", "close", "volume"]


class IntradayCandleSource(Protocol):
    async def get_historical_candles(
        self, instrument_key: str, interval: str, from_date: str, to_date: str
    ) -> list[list[object]]: ...


async def fetch_intraday_candles(
    source: IntradayCandleSource,
    *,
    symbol: str,
    instrument_key: str,
    day: date,
    interval: str = "1minute",
) -> pl.DataFrame:
    """Fetches one real trading day's minute bars for `symbol`. Upstox's own candle shape is
    `[timestamp, open, high, low, close, volume, open_interest]` -- open_interest is dropped
    here (equity intraday bars don't carry it; it's an F&O-only field)."""
    day_str = day.isoformat()
    raw_candles = await source.get_historical_candles(instrument_key, interval, day_str, day_str)

    if not raw_candles:
        return pl.DataFrame(schema=_EMPTY_SCHEMA)

    rows = [
        {
            "symbol": symbol,
            "timestamp": candle[0],
            "open": candle[1],
            "high": candle[2],
            "low": candle[3],
            "close": candle[4],
            "volume": candle[5],
        }
        for candle in raw_candles
    ]
    df = pl.DataFrame(rows)
    return df.with_columns(pl.col("timestamp").str.to_datetime(time_zone="Asia/Kolkata"))


_EMPTY_SCHEMA = {
    "symbol": pl.Utf8,
    "timestamp": pl.Datetime,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Int64,
}
