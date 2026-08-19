"""REL-078 (F&O Phase 2, part 2): src/data/ingest/pipeline.py::_fetch_managed. Proves the
resolve_instrument_key() fix -- a symbol that resolves to a real instrument now gets that real
instrument_key passed to MarketDataManager, not the bare symbol string. `resolve_instrument_key`
and `build_market_data_manager` are mocked (matching tests/unit/test_scheduled_sync.py's own
established convention); the real Postgres is used for `upsert_provenance`'s writes, cleaned up
afterward.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import delete

from src.core.db import get_session
from src.data.ingest import pipeline
from src.data.ingest.pipeline import _fetch_managed
from src.data.provenance import get_provenance
from src.data.providers.base import Candle, DataQualityReport
from src.data.providers.manager import MarketDataResult, MarketDataUnavailable
from src.models.market_data_provenance import MarketDataProvenance


class _FakeManager:
    def __init__(self, results: dict[str, MarketDataResult], failures: set[str]) -> None:
        self._results = results
        self._failures = failures
        self.calls: list[tuple[str, str, date, date]] = []

    def get_historical_data(
        self, *, instrument_key: str, symbol: str, start: date, end: date, timeframe: str
    ) -> MarketDataResult:
        self.calls.append((instrument_key, symbol, start, end))
        if symbol in self._failures:
            raise MarketDataUnavailable("boom", errors={"upstox_v3": "boom"})
        return self._results[symbol]


def _result(symbol: str, d: date) -> MarketDataResult:
    return MarketDataResult(
        candles=[
            Candle(
                timestamp=datetime(d.year, d.month, d.day, tzinfo=UTC),
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.5,
                volume=1000,
                open_interest=None,
                instrument_key="ignored",
                symbol=symbol,
                timeframe="1d",
                provider="upstox_v3",
            )
        ],
        provider_requested="upstox_v3",
        provider_used="upstox_v3",
        retrieved_at=datetime.now(UTC),
        quality=DataQualityReport(valid=True),
    )


def _cleanup_provenance(*symbols: str) -> None:
    with get_session() as session:
        session.execute(
            delete(MarketDataProvenance).where(MarketDataProvenance.symbol.in_(symbols))
        )
        session.commit()


def test_fetch_managed_passes_the_resolved_instrument_key_for_a_known_symbol(monkeypatch):
    symbol = f"PIPETESTCO{uuid.uuid4().hex[:6].upper()}"
    real_instrument_key = f"NSE_EQ|{symbol}"
    manager = _FakeManager(results={symbol: _result(symbol, date(2026, 8, 1))}, failures=set())

    monkeypatch.setattr(
        pipeline,
        "resolve_instrument_key",
        lambda session, sym, **kw: real_instrument_key if sym == symbol else None,
    )
    monkeypatch.setattr(pipeline, "build_market_data_manager", lambda: manager)

    try:
        rows = _fetch_managed([symbol], date(2026, 8, 1), date(2026, 8, 1))
        assert manager.calls == [(real_instrument_key, symbol, date(2026, 8, 1), date(2026, 8, 1))]
        assert rows.height == 1
    finally:
        _cleanup_provenance(symbol)


def test_fetch_managed_falls_back_to_the_bare_symbol_when_unresolvable(monkeypatch):
    """REL-078's own fix preserves this function's prior behavior for the rare case a symbol
    isn't a real active instruments-table row -- falls back to the bare symbol as
    instrument_key, matching what every symbol got before this fix, rather than skipping the
    symbol outright the way scheduled_sync.py does for its own broader universe scope."""
    symbol = f"PIPETESTCO{uuid.uuid4().hex[:6].upper()}"
    manager = _FakeManager(results={symbol: _result(symbol, date(2026, 8, 1))}, failures=set())

    monkeypatch.setattr(pipeline, "resolve_instrument_key", lambda session, sym, **kw: None)
    monkeypatch.setattr(pipeline, "build_market_data_manager", lambda: manager)

    try:
        rows = _fetch_managed([symbol], date(2026, 8, 1), date(2026, 8, 1))
        assert manager.calls == [(symbol, symbol, date(2026, 8, 1), date(2026, 8, 1))]
        assert rows.height == 1
    finally:
        _cleanup_provenance(symbol)


def test_fetch_managed_skips_a_symbol_the_manager_cannot_serve_and_continues(monkeypatch):
    ok_symbol = f"PIPETESTOK{uuid.uuid4().hex[:6].upper()}"
    failing_symbol = f"PIPETESTFAIL{uuid.uuid4().hex[:6].upper()}"
    manager = _FakeManager(
        results={ok_symbol: _result(ok_symbol, date(2026, 8, 1))}, failures={failing_symbol}
    )

    monkeypatch.setattr(pipeline, "resolve_instrument_key", lambda session, sym, **kw: None)
    monkeypatch.setattr(pipeline, "build_market_data_manager", lambda: manager)

    try:
        rows = _fetch_managed([failing_symbol, ok_symbol], date(2026, 8, 1), date(2026, 8, 1))
        assert rows.height == 1
        assert rows["symbol"].to_list() == [ok_symbol]
    finally:
        _cleanup_provenance(ok_symbol, failing_symbol)


def test_fetch_managed_writes_real_provenance_for_a_succeeding_symbol(monkeypatch):
    symbol = f"PIPETESTPROV{uuid.uuid4().hex[:6].upper()}"
    manager = _FakeManager(results={symbol: _result(symbol, date(2026, 8, 1))}, failures=set())

    monkeypatch.setattr(pipeline, "resolve_instrument_key", lambda session, sym, **kw: None)
    monkeypatch.setattr(pipeline, "build_market_data_manager", lambda: manager)

    try:
        _fetch_managed([symbol], date(2026, 8, 1), date(2026, 8, 1))
        with get_session() as session:
            row = get_provenance(session, symbol)
        assert row is not None
        assert row.provider == "upstox_v3"
    finally:
        _cleanup_provenance(symbol)
