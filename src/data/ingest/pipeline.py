"""CLI entrypoint for Phase 1 data ingestion (Epic: Historical Data Lake).

Safe to re-run for daily updates: the writer de-duplicates on (symbol, date).

Usage:
    python -m src.data.ingest.pipeline --source bhavcopy --symbols RELIANCE,TCS,INFY \\
        --start 2024-01-01 --end 2024-12-31
"""

import argparse
from datetime import date

import structlog

from src.core.config import get_settings
from src.data.ingest.base import EODDataSourceAdapter
from src.data.ingest.bhavcopy import BhavcopyAdapter
from src.data.ingest.writer import ParquetLakeWriter
from src.data.ingest.yfinance_adapter import YFinanceAdapter

logger = structlog.get_logger(__name__)

ADAPTERS: dict[str, type[EODDataSourceAdapter]] = {
    "bhavcopy": BhavcopyAdapter,
    "yfinance": YFinanceAdapter,
}


def run(source: str, symbols: list[str], start: date, end: date) -> int:
    adapter = ADAPTERS[source]()
    writer = ParquetLakeWriter(get_settings().data_lake_root / "ohlcv_daily")

    rows = adapter.fetch(symbols, start, end)
    written = writer.write(rows)
    logger.info("ingestion_complete", source=source, symbols=len(symbols), rows_written=written)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest EOD OHLCV data into the TradingOS Parquet data lake."
    )
    parser.add_argument("--source", choices=sorted(ADAPTERS), default="bhavcopy")
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
