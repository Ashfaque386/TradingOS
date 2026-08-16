"""REL-071 (Phase 2): src/data/ingest/instrument_sync.py. `_parse_record` is tested as pure
logic (no DB); `InstrumentSyncService.sync()`'s real reactivate-then-upsert behavior is tested
against the real dev Postgres (matching this codebase's own convention -- see
tests/integration/test_market_data_router.py's `_seed_corporate_action`/`_cleanup_corporate_action`
-- no DB layer is mocked, only the external HTTP file download). Uses a fake `exchange="TESTEX"`
so these runs never touch the real synced NSE/BSE rows a live sync (see this phase's own
verification notes) already populated in this environment.
"""

from __future__ import annotations

import gzip
import json
from typing import Any

import httpx
import pytest
from sqlalchemy import delete

from src.core.db import get_session
from src.data.ingest.instrument_sync import PROVIDER, InstrumentSyncService, _parse_record
from src.models.instrument import Instrument

_TEST_EXCHANGE = "TESTEX"


def _cleanup_test_exchange() -> None:
    with get_session() as session:
        session.execute(
            delete(Instrument).where(
                Instrument.provider == PROVIDER, Instrument.exchange == _TEST_EXCHANGE
            )
        )
        session.commit()


@pytest.fixture(autouse=True)
def _isolate_test_exchange():
    _cleanup_test_exchange()
    yield
    _cleanup_test_exchange()


def test_parse_record_accepts_a_real_shaped_equity_record():
    record = {
        "instrument_type": "EQ",
        "instrument_key": "NSE_EQ|INE002A01018",
        "trading_symbol": "RELIANCE",
        "name": "Reliance Industries Ltd",
        "segment": "NSE_EQ",
        "isin": "INE002A01018",
        "lot_size": 1,
        "tick_size": 0.05,
    }
    row = _parse_record(record, exchange="NSE")
    assert row == {
        "instrument_key": "NSE_EQ|INE002A01018",
        "exchange": "NSE",
        "segment": "NSE_EQ",
        "symbol": "RELIANCE",
        "name": "Reliance Industries Ltd",
        "instrument_type": "EQ",
        "isin": "INE002A01018",
        "expiry": None,
        "strike": None,
        "lot_size": 1,
        "tick_size": 0.05,
    }


def test_parse_record_accepts_a_real_shaped_index_record_with_no_isin_or_lot_size():
    # Real finding from this phase's own live sync: index rows genuinely carry none of
    # isin/lot_size/tick_size -- not a malformed record, the real Upstox schema for INDEX.
    record = {
        "instrument_type": "INDEX",
        "instrument_key": "NSE_INDEX|Nifty 50",
        "trading_symbol": "NIFTY",
        "name": "Nifty 50",
        "segment": "NSE_INDEX",
    }
    row = _parse_record(record, exchange="NSE")
    assert row is not None
    assert row["symbol"] == "NIFTY"
    assert row["name"] == "Nifty 50"
    assert row["isin"] is None
    assert row["lot_size"] is None
    assert row["tick_size"] is None


def test_parse_record_rejects_an_unsupported_instrument_type():
    record = {
        "instrument_type": "FUT",
        "instrument_key": "NSE_FO|12345",
        "trading_symbol": "NIFTY24DECFUT",
        "name": "NIFTY FUT",
        "segment": "NSE_FO",
    }
    assert _parse_record(record, exchange="NSE") is None


def test_parse_record_rejects_a_record_missing_a_required_field():
    record = {
        "instrument_type": "EQ",
        "instrument_key": "NSE_EQ|SOMETHING",
        "trading_symbol": "",  # falsy -- treated as missing, not a real symbol
        "name": "Something Ltd",
        "segment": "NSE_EQ",
    }
    assert _parse_record(record, exchange="NSE") is None


def test_fetch_raw_downloads_and_gunzips_the_real_response_shape(monkeypatch):
    payload: list[dict[str, Any]] = [{"instrument_type": "EQ", "trading_symbol": "FAKE"}]
    compressed = gzip.compress(json.dumps(payload).encode())

    def _fake_get(self: httpx.Client, url: str) -> httpx.Response:
        assert url == "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
        return httpx.Response(200, content=compressed, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", _fake_get)

    with InstrumentSyncService() as service:
        data = service.fetch_raw("NSE")
    assert data == payload


def _canned_records(*, active_symbol: str, dropped: bool = False) -> list[dict[str, Any]]:
    records = [
        {
            "instrument_type": "EQ",
            "instrument_key": f"{_TEST_EXCHANGE}_EQ|{active_symbol}",
            "trading_symbol": active_symbol,
            "name": f"{active_symbol} Test Co",
            "segment": f"{_TEST_EXCHANGE}_EQ",
            "isin": "INE_TEST_0001",
            "lot_size": 1,
            "tick_size": 0.05,
        }
    ]
    if not dropped:
        records.append(
            {
                "instrument_type": "INDEX",
                "instrument_key": f"{_TEST_EXCHANGE}_INDEX|TESTIDX",
                "trading_symbol": "TESTIDX",
                "name": "Test Index",
                "segment": f"{_TEST_EXCHANGE}_INDEX",
            }
        )
    return records


def test_sync_inserts_real_active_rows_from_the_fetched_file(monkeypatch):
    monkeypatch.setattr(
        InstrumentSyncService,
        "fetch_raw",
        lambda self, exchange: _canned_records(active_symbol="ALPHA"),
    )
    with InstrumentSyncService() as service, get_session() as session:
        written = service.sync(session, _TEST_EXCHANGE)
    assert written == 2

    with get_session() as session:
        rows = {
            row.symbol: row
            for row in session.query(Instrument).filter(
                Instrument.provider == PROVIDER, Instrument.exchange == _TEST_EXCHANGE
            )
        }
    assert set(rows) == {"ALPHA", "TESTIDX"}
    assert rows["ALPHA"].is_active is True
    assert rows["ALPHA"].isin == "INE_TEST_0001"
    assert rows["TESTIDX"].is_active is True
    assert rows["TESTIDX"].isin is None


def test_sync_reactivation_deactivates_a_symbol_dropped_from_the_fresh_file(monkeypatch):
    monkeypatch.setattr(
        InstrumentSyncService,
        "fetch_raw",
        lambda self, exchange: _canned_records(active_symbol="BETA"),
    )
    with InstrumentSyncService() as service, get_session() as session:
        service.sync(session, _TEST_EXCHANGE)

    # Second sync's file no longer lists "TESTIDX" -- a real delisting must go inactive, not
    # be deleted (this module's own stated honesty rule).
    monkeypatch.setattr(
        InstrumentSyncService,
        "fetch_raw",
        lambda self, exchange: _canned_records(active_symbol="BETA", dropped=True),
    )
    with InstrumentSyncService() as service, get_session() as session:
        written = service.sync(session, _TEST_EXCHANGE)
    assert written == 1

    with get_session() as session:
        rows = {
            row.symbol: row
            for row in session.query(Instrument).filter(
                Instrument.provider == PROVIDER, Instrument.exchange == _TEST_EXCHANGE
            )
        }
    assert rows["BETA"].is_active is True
    assert rows["TESTIDX"].is_active is False  # still present, honestly inactive -- not deleted


def test_sync_upsert_updates_a_changed_field_on_a_re_synced_row(monkeypatch):
    monkeypatch.setattr(
        InstrumentSyncService,
        "fetch_raw",
        lambda self, exchange: _canned_records(active_symbol="GAMMA"),
    )
    with InstrumentSyncService() as service, get_session() as session:
        service.sync(session, _TEST_EXCHANGE)

    changed = _canned_records(active_symbol="GAMMA")
    changed[0]["name"] = "GAMMA Test Co Renamed"
    monkeypatch.setattr(InstrumentSyncService, "fetch_raw", lambda self, exchange: changed)
    with InstrumentSyncService() as service, get_session() as session:
        service.sync(session, _TEST_EXCHANGE)

    with get_session() as session:
        row = (
            session.query(Instrument)
            .filter(
                Instrument.provider == PROVIDER,
                Instrument.exchange == _TEST_EXCHANGE,
                Instrument.symbol == "GAMMA",
            )
            .one()
        )
    assert row.name == "GAMMA Test Co Renamed"
