from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, UUIDPKMixin


class MarketDataProvenance(Base, UUIDPKMixin, TimestampMixin):
    """REL-073 (Phase 4 of the Upstox V3 + yfinance dual market-data system). A real, small,
    one-row-per-symbol record of the most recent successful managed/scheduled OHLCV fetch --
    closes the gap `run_real_backtest()` (`src/engine/sandbox/backtest_runner.py`) can't answer
    on its own: it reads straight from the Parquet data lake (`DataLake.read_symbol()`), which
    carries no per-row provider/fetch-time column, so "which provider supplied this backtest's
    data" has no real source of truth without this table.

    Deliberately NOT a per-row/full audit trail (matches this phase's own approved scope: "prefer
    ... not must ... deliberately not a full data-snapshot/hash system") -- upserted (never
    appended) by `src/data/ingest/pipeline.py`'s `_fetch_managed()` and
    `src/data/ingest/scheduled_sync.py`'s per-symbol loop after every real successful managed
    fetch, so this always reflects only the LAST managed ingestion for a symbol, honestly stated
    as such wherever it's surfaced -- never a claim that every historical row in a backtest's
    date range came from this exact provider/timestamp."""

    __tablename__ = "market_data_provenance"

    symbol: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
