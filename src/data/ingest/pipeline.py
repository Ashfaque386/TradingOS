"""CLI entrypoint for Phase 1 data ingestion (Epic: Historical Data Lake).

Safe to re-run for daily updates: the writer de-duplicates on (symbol, date).

REL-070 (Phase 1 of the Upstox V3 + yfinance dual market-data system): `--source managed` is
the new default, going through `MarketDataManager` (Upstox V3 primary, yfinance fallback, real
per-symbol failover) instead of a single hardcoded adapter. `bhavcopy` remains available and
untouched -- a real, distinct NSE bulk EOD source outside the Upstox/yfinance failover pair this
release adds. `yfinance` remains available too, as a direct, `MarketDataManager`-bypassing choice
for local debugging (see src/data/providers/yahoo_finance.py's module docstring).

Usage:
    python -m src.data.ingest.pipeline --source managed --symbols RELIANCE,TCS,INFY \\
        --start 2024-01-01 --end 2024-12-31
"""

import argparse
from datetime import date

import polars as pl
import structlog

from src.core.config import get_settings
from src.data.ingest.base import EODDataSourceAdapter
from src.data.ingest.bhavcopy import BhavcopyAdapter
from src.data.ingest.writer import ParquetLakeWriter
from src.data.ingest.yfinance_adapter import YFinanceAdapter
from src.data.providers.base import Candle
from src.data.providers.manager import MarketDataUnavailable, build_market_data_manager

logger = structlog.get_logger(__name__)

ADAPTERS: dict[str, type[EODDataSourceAdapter]] = {
    "bhavcopy": BhavcopyAdapter,
    "yfinance": YFinanceAdapter,
}
_MANAGED_SOURCE = "managed"


def _candles_to_eod_dataframe(symbol: str, candles: list[Candle]) -> pl.DataFrame:
    if not candles:
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
    return pl.DataFrame(
        {
            "symbol": [symbol] * len(candles),
            "date": [c.timestamp.date() for c in candles],
            "open": [c.open for c in candles],
            "high": [c.high for c in candles],
            "low": [c.low for c in candles],
            "close": [c.close for c in candles],
            "volume": [c.volume for c in candles],
        }
    )


def _fetch_managed(symbols: list[str], start: date, end: date) -> pl.DataFrame:
    """Real per-symbol failover: a symbol Upstox can't serve (today, always -- no real
    instrument_key resolution exists until Phase 2/REL-071) falls over to yfinance
    honestly, per this module's own docstring; a symbol neither provider has anything for is
    logged and skipped, never silently fabricated."""
    manager = build_market_data_manager()
    frames: list[pl.DataFrame] = []
    for symbol in symbols:
        try:
            result = manager.get_historical_data(
                instrument_key=symbol, symbol=symbol, start=start, end=end, timeframe="1d"
            )
        except MarketDataUnavailable as exc:
            logger.warning("managed_ingestion_symbol_failed", symbol=symbol, errors=exc.errors)
            continue
        logger.info(
            "managed_ingestion_symbol_succeeded",
            symbol=symbol,
            provider_requested=result.provider_requested,
            provider_used=result.provider_used,
            rows=len(result.candles),
        )
        frames.append(_candles_to_eod_dataframe(symbol, result.candles))

    if not frames:
        return _candles_to_eod_dataframe("", [])
    return pl.concat(frames).sort(["symbol", "date"])


def run(source: str, symbols: list[str], start: date, end: date) -> int:
    writer = ParquetLakeWriter(get_settings().data_lake_root / "ohlcv_daily")

    rows = (
        _fetch_managed(symbols, start, end)
        if source == _MANAGED_SOURCE
        else ADAPTERS[source]().fetch(symbols, start, end)
    )
    written = writer.write(rows)
    logger.info("ingestion_complete", source=source, symbols=len(symbols), rows_written=written)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest EOD OHLCV data into the TradingOS Parquet data lake."
    )
    parser.add_argument(
        "--source", choices=[_MANAGED_SOURCE, *sorted(ADAPTERS)], default=_MANAGED_SOURCE
    )
    parser.add_argument(
        "--symbols", required=True, help="Comma-separated NSE symbols, e.g. RELIANCE,TCS,INFY"
    )
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    run(args.source, symbols, args.start, args.end)


if __name__ == "__main__":
    main()
