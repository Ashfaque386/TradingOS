"""Yahoo Finance adapter — secondary/convenience EOD source.

Useful for quick local development or symbols not cleanly covered by bhavcopy
(e.g. indices). Not the source of truth for production ingestion: no Indian
STT/tax metadata, and adjusted-close handling differs from NSE's raw prices.
NSE symbols need a ".NS" suffix for Yahoo (e.g. "RELIANCE" -> "RELIANCE.NS").
"""

from datetime import date

import polars as pl
import structlog
import yfinance as yf

from src.data.ingest.base import EODDataSourceAdapter

logger = structlog.get_logger(__name__)


class YFinanceAdapter(EODDataSourceAdapter):
    def fetch(self, symbols: list[str], start: date, end: date) -> pl.DataFrame:
        frames: list[pl.DataFrame] = []
        for symbol in symbols:
            yahoo_symbol = symbol if symbol.endswith(".NS") else f"{symbol}.NS"
            try:
                history = yf.Ticker(yahoo_symbol).history(start=start, end=end, interval="1d")
            except Exception as exc:  # yfinance raises assorted network/library errors
                logger.warning("yfinance_fetch_failed", symbol=symbol, error=str(exc))
                continue
            if history.empty:
                continue

            df = pl.from_pandas(history.reset_index()).select(
                pl.lit(symbol).alias("symbol"),
                pl.col("Date").cast(pl.Date).alias("date"),
                pl.col("Open").alias("open"),
                pl.col("High").alias("high"),
                pl.col("Low").alias("low"),
                pl.col("Close").alias("close"),
                pl.col("Volume").cast(pl.Int64).alias("volume"),
            )
            frames.append(df)

        if not frames:
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
        return pl.concat(frames).sort(["symbol", "date"])
