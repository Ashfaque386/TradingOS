from datetime import date

from sqlalchemy import Boolean, Date, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, UUIDPKMixin


class Instrument(Base, UUIDPKMixin, TimestampMixin):
    """REL-071 (Phase 2 of the Upstox V3 + yfinance dual market-data system). A real, locally-
    synced copy of Upstox's own real instrument master (`src/data/ingest/instrument_sync.py`
    downloads and parses the real, daily-refreshed `https://assets.upstox.com/market-quote/
    instruments/exchange/{NSE|BSE}.json.gz` files) -- the piece Phase 1 stated as an honest gap:
    `UpstoxV3Provider` needs a real `instrument_key` (e.g. "NSE_EQ|INE002A01018"), and nothing in
    this codebase could resolve a bare symbol like "RELIANCE" into one until this table exists.

    `instrument_key` is the real Upstox identifier and the only safe way to reference an
    instrument across syncs -- `exchange_token` (not stored here) can be reused by the exchange
    for a different instrument after expiry, per Upstox's own documentation, so `symbol` alone is
    never treated as a stable identifier either (two different real rows can legitimately share a
    `symbol` across `instrument_type`s, e.g. an equity and a future on the same underlying).

    `is_active=False` (never a row deletion) is how a real delisting is recorded once Upstox's
    own file stops listing an instrument -- `instrument_sync.py` marks every existing row for a
    given `(provider, exchange)` inactive before each real sync, then reactivates whatever the
    fresh file actually lists -- matching this codebase's established "honest state, never
    silently discard" convention (e.g. `AgentControlState`'s own no-row-means-enabled default)."""

    __tablename__ = "instruments"
    __table_args__ = (
        UniqueConstraint("provider", "instrument_key", name="uq_instruments_provider_key"),
        Index("ix_instruments_symbol", "symbol"),
        Index("ix_instruments_exchange_type", "exchange", "instrument_type"),
    )

    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    instrument_key: Mapped[str] = mapped_column(String(100), nullable=False)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False)
    segment: Mapped[str] = mapped_column(String(20), nullable=False)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    instrument_type: Mapped[str] = mapped_column(String(20), nullable=False)
    isin: Mapped[str | None] = mapped_column(String(20))
    expiry: Mapped[date | None] = mapped_column(Date)
    strike: Mapped[float | None] = mapped_column(Numeric(12, 2))
    lot_size: Mapped[int | None] = mapped_column(Integer)
    tick_size: Mapped[float | None] = mapped_column(Numeric(10, 4))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
