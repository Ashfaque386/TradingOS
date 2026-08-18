"""REL-073 (Phase 4 of the Upstox V3 + yfinance dual market-data system): the real read/write
surface for `market_data_provenance` (`src/models/market_data_provenance.py`) -- a small,
one-row-per-symbol record of the most recent successful managed/scheduled OHLCV fetch, written
by `src/data/ingest/pipeline.py`'s `_fetch_managed()` and `src/data/ingest/scheduled_sync.py`'s
per-symbol loop, read by `src/engine/sandbox/backtest_runner.py`'s `run_real_backtest()`.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.models.market_data_provenance import MarketDataProvenance


def upsert_provenance(
    session: Session, *, symbol: str, provider: str, retrieved_at: datetime
) -> None:
    """Real `INSERT ... ON CONFLICT (symbol) DO UPDATE` -- matches
    `src/data/ingest/instrument_sync.py`'s own established upsert pattern. Overwrites, never
    appends: this table only ever tracks the LAST managed ingestion for a symbol."""
    stmt = insert(MarketDataProvenance).values(
        symbol=symbol, provider=provider, retrieved_at=retrieved_at
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_market_data_provenance_symbol",
        set_={"provider": provider, "retrieved_at": retrieved_at},
    )
    session.execute(stmt)
    session.commit()


def get_provenance(session: Session, symbol: str) -> MarketDataProvenance | None:
    """`None` when no managed/scheduled fetch has ever written this symbol -- a real, honest
    "unknown," never guessed (e.g. a symbol only ever ingested via the direct `bhavcopy`/
    `yfinance` CLI adapters, which bypass `MarketDataManager` entirely and so never call
    `upsert_provenance`)."""
    return session.scalar(select(MarketDataProvenance).where(MarketDataProvenance.symbol == symbol))
