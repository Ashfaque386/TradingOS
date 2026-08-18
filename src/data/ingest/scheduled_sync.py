"""REL-072 (Phase 3 of the Upstox V3 + yfinance dual market-data system): real scheduled
incremental ingestion, closing the last manual-step gap Phase 1/2 left open. Phases 1 (REL-070)
and 2 (REL-071) built real failover and real instrument resolution, but a human still had to run
`python -m src.data.ingest.pipeline` by hand for any of it to reach the data lake.

`src/agents/scheduler.py`'s own `run_market_data_ingestion()` wrapper calls
`run_incremental_ingestion()` below on a daily cron, before the freshness-gated research cycle.

Real symbol scope (the one real design decision here, see this phase's own approved plan): every
symbol already tracked in the lake (kept fresh) UNION every real `Strategy.universe[0]` value
(closes REL-070's original gap -- a strategy referencing a real, discoverable instrument that was
never manually ingested now gets it automatically, no CLI step). A universe entry that doesn't
resolve to any real instrument (e.g. the already-confirmed "NIFTY TECHNOLOGY", not a real NSE
index) is honestly logged and skipped every run, never fabricated or retried needlessly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.config import get_settings
from src.core.db import get_session
from src.data.datalake.query import DataLake
from src.data.ingest.instrument_sync import InstrumentSyncService
from src.data.ingest.pipeline import candles_to_eod_dataframe
from src.data.ingest.writer import ParquetLakeWriter
from src.data.instruments import resolve_instrument_key
from src.data.providers.manager import MarketDataUnavailable, build_market_data_manager
from src.models.strategy import Strategy

logger = structlog.get_logger(__name__)

# ~2 real trading years -- long enough for the Walk-Forward/Monte Carlo windows this codebase
# already uses elsewhere, for a symbol that has never been ingested before.
INITIAL_BACKFILL_DAYS = 730


@dataclass
class IncrementalIngestionSummary:
    instruments_synced: int = 0
    symbols_backfilled: list[str] = field(default_factory=list)
    symbols_topped_up: list[str] = field(default_factory=list)
    symbols_already_fresh: list[str] = field(default_factory=list)
    symbols_skipped_unresolvable: list[str] = field(default_factory=list)
    symbols_failed: list[str] = field(default_factory=list)


def _target_symbols(lake: DataLake, session: Session) -> set[str]:
    symbols = set(lake.list_symbols())
    rows = session.scalars(select(Strategy.universe).where(Strategy.universe.isnot(None)))
    for universe in rows:
        if universe:
            symbols.add(universe[0])
    return symbols


def run_incremental_ingestion() -> IncrementalIngestionSummary:
    settings = get_settings()
    lake = DataLake(settings.data_lake_root / "ohlcv_daily")
    writer = ParquetLakeWriter(settings.data_lake_root / "ohlcv_daily")
    summary = IncrementalIngestionSummary()
    today = date.today()

    with get_session() as session:
        try:
            summary.instruments_synced = InstrumentSyncService().sync(session, "NSE")
        except Exception as exc:  # noqa: BLE001 -- a failed instrument-master sync must not
            # block the OHLCV top-up below; resolve_instrument_key() just falls back to whatever
            # the table already had from a prior real sync.
            logger.warning("scheduled_ingestion_instrument_sync_failed", error=str(exc))

        symbols = _target_symbols(lake, session)
        manager = build_market_data_manager()

        for symbol in sorted(symbols):
            instrument_key = resolve_instrument_key(session, symbol, exchange="NSE")
            if instrument_key is None:
                logger.info("scheduled_ingestion_symbol_unresolvable", symbol=symbol)
                summary.symbols_skipped_unresolvable.append(symbol)
                continue

            latest = lake.latest_date(symbol)
            is_backfill = latest is None
            start = (
                today - timedelta(days=INITIAL_BACKFILL_DAYS)
                if latest is None
                else latest + timedelta(days=1)
            )
            if start > today:
                summary.symbols_already_fresh.append(symbol)
                continue

            try:
                result = manager.get_historical_data(
                    instrument_key=instrument_key,
                    symbol=symbol,
                    start=start,
                    end=today,
                    timeframe="1d",
                )
            except MarketDataUnavailable as exc:
                logger.warning(
                    "scheduled_ingestion_symbol_failed", symbol=symbol, errors=exc.errors
                )
                summary.symbols_failed.append(symbol)
                continue

            if not result.candles:
                summary.symbols_already_fresh.append(symbol)
                continue

            written = writer.write(candles_to_eod_dataframe(symbol, result.candles))
            (summary.symbols_backfilled if is_backfill else summary.symbols_topped_up).append(
                symbol
            )
            logger.info(
                "scheduled_ingestion_symbol_succeeded",
                symbol=symbol,
                backfill=is_backfill,
                provider_used=result.provider_used,
                rows_written=written,
            )

    logger.info(
        "scheduled_ingestion_complete",
        instruments_synced=summary.instruments_synced,
        backfilled=len(summary.symbols_backfilled),
        topped_up=len(summary.symbols_topped_up),
        already_fresh=len(summary.symbols_already_fresh),
        unresolvable=len(summary.symbols_skipped_unresolvable),
        failed=len(summary.symbols_failed),
    )
    return summary
