"""Yahoo Finance adapter — secondary/convenience EOD source.

Useful for quick local development or symbols not cleanly covered by bhavcopy
(e.g. indices). Not the source of truth for production ingestion: no Indian
STT/tax metadata, and adjusted-close handling differs from NSE's raw prices.

REL-070 (Phase 1 of the Upstox V3 + yfinance dual market-data system): symbol mapping (the real
".NS" suffix logic, including the REL-016 index-ticker exception below) now lives in exactly one
place, `src/data/providers/yahoo_finance.py::YahooSymbolMapper`, and this adapter delegates to it
rather than duplicating it -- `YahooFinanceProvider` (the same module) is the new real fallback
path `MarketDataManager` uses; this adapter remains as a direct, `MarketDataManager`-bypassing
CLI option (`python -m src.data.ingest.pipeline --source yfinance`) for local debugging.

REL-016 E16.2 (GLH-08): index tickers (e.g. "^NSEI" for Nifty 50) must NOT get the ".NS" suffix
-- Yahoo has no "^NSEI.NS" ticker, so the un-guarded suffix silently returned an empty history
for every index symbol, confirmed the hard way while ingesting real Nifty 50 data for the first
time. `^NSEBANK`/`^INDIAVIX` (src/agents/tools/skills.py) already call yfinance directly without
suffixing for the same reason.
"""

from datetime import date

import polars as pl
import structlog
import yfinance as yf

from src.data.ingest.base import EODDataSourceAdapter
from src.data.providers.yahoo_finance import YahooSymbolMapper

logger = structlog.get_logger(__name__)


class YFinanceAdapter(EODDataSourceAdapter):
    def fetch(self, symbols: list[str], start: date, end: date) -> pl.DataFrame:
        frames: list[pl.DataFrame] = []
        for symbol in symbols:
            yahoo_symbol = YahooSymbolMapper.to_yahoo_symbol(symbol)
            if yahoo_symbol is None:
                logger.warning("yfinance_symbol_unmapped", symbol=symbol)
                continue
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
