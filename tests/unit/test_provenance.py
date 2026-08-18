"""REL-073 (Phase 4): src/data/provenance.py against the real dev Postgres -- a real, small
upsert table, no external I/O to mock."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete

from src.core.db import get_session
from src.data.provenance import get_provenance, upsert_provenance
from src.models.market_data_provenance import MarketDataProvenance

_SYMBOL = f"PROVTEST{uuid.uuid4().hex[:8].upper()}"


def teardown_function() -> None:
    with get_session() as session:
        session.execute(delete(MarketDataProvenance).where(MarketDataProvenance.symbol == _SYMBOL))
        session.commit()


def test_get_provenance_returns_none_for_a_symbol_never_written():
    with get_session() as session:
        assert get_provenance(session, _SYMBOL) is None


def test_upsert_provenance_inserts_a_real_row():
    retrieved_at = datetime(2026, 8, 18, 5, 0, tzinfo=UTC)
    with get_session() as session:
        upsert_provenance(session, symbol=_SYMBOL, provider="upstox_v3", retrieved_at=retrieved_at)

    with get_session() as session:
        row = get_provenance(session, _SYMBOL)
    assert row is not None
    assert row.symbol == _SYMBOL
    assert row.provider == "upstox_v3"
    assert row.retrieved_at == retrieved_at


def test_upsert_provenance_overwrites_the_existing_row_not_appends():
    first = datetime(2026, 8, 17, 5, 0, tzinfo=UTC)
    second = datetime(2026, 8, 18, 5, 0, tzinfo=UTC)
    with get_session() as session:
        upsert_provenance(session, symbol=_SYMBOL, provider="upstox_v3", retrieved_at=first)
    with get_session() as session:
        upsert_provenance(session, symbol=_SYMBOL, provider="yfinance", retrieved_at=second)

    with get_session() as session:
        row = get_provenance(session, _SYMBOL)
    assert row is not None
    assert row.provider == "yfinance"
    assert row.retrieved_at == second

    with get_session() as session:
        count = (
            session.query(MarketDataProvenance)
            .filter(MarketDataProvenance.symbol == _SYMBOL)
            .count()
        )
    assert count == 1
