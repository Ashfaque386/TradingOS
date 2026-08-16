"""Real instrument query surface (REL-071, Phase 2 of the Upstox V3 + yfinance dual market-data
system) -- the read side of `src/data/ingest/instrument_sync.py`'s real, locally-synced
`instruments` table. Every query here is scoped to `is_active=True` real rows only (a real
delisting stays in the table, honestly inactive, but never surfaces as a live, tradable
instrument to a caller).
"""

from __future__ import annotations

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from src.models.instrument import Instrument


def _filtered_query(
    *, query: str | None, exchange: str | None, instrument_type: str | None
) -> Select[tuple[Instrument]]:
    stmt = select(Instrument).where(Instrument.is_active.is_(True))
    if query:
        pattern = f"%{query}%"
        # Real finding while verifying this module: Upstox's own Nifty 50 row has
        # trading_symbol="NIFTY" but name="Nifty 50" -- searching `symbol` alone would miss it,
        # so both real columns are checked.
        stmt = stmt.where(or_(Instrument.symbol.ilike(pattern), Instrument.name.ilike(pattern)))
    if exchange:
        stmt = stmt.where(Instrument.exchange == exchange)
    if instrument_type:
        stmt = stmt.where(Instrument.instrument_type == instrument_type)
    return stmt


def search(
    session: Session,
    *,
    query: str | None = None,
    exchange: str | None = None,
    instrument_type: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> tuple[list[Instrument], int]:
    """Real pagination: returns this page's rows plus the real total count matching the same
    filters (so a caller can compute total pages), not just the page slice."""
    stmt = _filtered_query(query=query, exchange=exchange, instrument_type=instrument_type)
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        session.scalars(
            stmt.order_by(Instrument.symbol).offset((page - 1) * page_size).limit(page_size)
        )
    )
    return rows, total


def get_equities(session: Session, exchange: str) -> list[Instrument]:
    stmt = _filtered_query(query=None, exchange=exchange, instrument_type="EQ")
    return list(session.scalars(stmt.order_by(Instrument.symbol)))


def get_indices(session: Session, exchange: str) -> list[Instrument]:
    stmt = _filtered_query(query=None, exchange=exchange, instrument_type="INDEX")
    return list(session.scalars(stmt.order_by(Instrument.symbol)))


def resolve_instrument_key(session: Session, symbol: str, *, exchange: str = "NSE") -> str | None:
    """Exact `symbol` match against real `is_active` rows -- the real function Phase 3 will call
    to stop passing bare symbols to `UpstoxV3Provider` as if they were instrument keys. Returns
    `None` (never a guess) when no real active instrument matches."""
    row = session.scalar(
        select(Instrument).where(
            Instrument.symbol == symbol,
            Instrument.exchange == exchange,
            Instrument.is_active.is_(True),
        )
    )
    return row.instrument_key if row else None
