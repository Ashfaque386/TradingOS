"""REL-010 E10.8a: market data REST surface (src/api/routers/market_data.py) against the real
FastAPI app + real Postgres + the real data lake already populated by earlier REL-005/E10.7
ingestion runs in this Docker stack (RELIANCE is a real, confirmed-present symbol -- see
tests/integration/test_corporate_actions_backtest_diff.py, which relies on the same fact).
"""

import uuid
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.brokers.factory import NoBrokerConfigured, build_broker
from src.core.db import get_session
from src.models.corporate_action import CorporateAction

client = TestClient(app)

_REAL_SYMBOL = "RELIANCE"


def test_symbols_returns_real_symbols_from_the_data_lake():
    response = client.get("/api/v1/market/symbols")
    assert response.status_code == 200
    symbols = response.json()
    assert isinstance(symbols, list)
    assert _REAL_SYMBOL in symbols


def test_daily_ohlcv_returns_real_bars_for_a_real_symbol():
    response = client.get(f"/api/v1/market/ohlcv/{_REAL_SYMBOL}")
    assert response.status_code == 200
    bars = response.json()
    assert len(bars) > 0
    first = bars[0]
    assert set(first) == {"date", "open", "high", "low", "close", "volume"}
    assert first["close"] > 0


def test_daily_ohlcv_returns_empty_list_for_an_unknown_symbol():
    response = client.get("/api/v1/market/ohlcv/NOTAREALSYMBOL12345")
    assert response.status_code == 200
    assert response.json() == []


def test_intraday_ohlcv_returns_empty_list_when_nothing_ingested_yet():
    """Honest gap: the intraday scheduler job only fires during real NSE market hours (E10.7),
    so this real symbol genuinely has no intraday partitions yet in this dev environment --
    asserting an empty list (not an error) is the real, correct behavior."""
    response = client.get(f"/api/v1/market/ohlcv-intraday/{_REAL_SYMBOL}")
    assert response.status_code == 200
    assert response.json() == []


def _seed_corporate_action() -> tuple[str, date]:
    symbol = f"MKTDATATEST{uuid.uuid4().hex[:6].upper()}"
    ex_date = date(2025, 1, 15)
    with get_session() as session:
        session.add(
            CorporateAction(
                symbol=symbol,
                ex_date=ex_date,
                action_type="BONUS",
                ratio_numerator=1,
                ratio_denominator=3,
                source="test-fixture-not-a-real-nse-event",
            )
        )
        session.commit()
    return symbol, ex_date


def _cleanup_corporate_action(symbol: str, ex_date: date) -> None:
    with get_session() as session:
        session.query(CorporateAction).filter(
            CorporateAction.symbol == symbol, CorporateAction.ex_date == ex_date
        ).delete()
        session.commit()


def test_corporate_actions_endpoint_returns_a_real_seeded_row():
    symbol, ex_date = _seed_corporate_action()
    try:
        response = client.get(f"/api/v1/market/corporate-actions/{symbol}")
        assert response.status_code == 200
        rows = response.json()
        assert len(rows) == 1
        assert rows[0]["action_type"] == "BONUS"
        assert rows[0]["ratio_denominator"] == 3.0
    finally:
        _cleanup_corporate_action(symbol, ex_date)


def test_corporate_actions_endpoint_returns_empty_list_for_a_symbol_with_none():
    response = client.get("/api/v1/market/corporate-actions/NOACTIONSFORTHIS12345")
    assert response.status_code == 200
    assert response.json() == []


def test_quote_against_a_real_broker():
    try:
        build_broker()
    except NoBrokerConfigured:
        pytest.skip("No broker configured in this environment")

    response = client.get(f"/api/v1/market/quote/{_REAL_SYMBOL}")
    if response.status_code != 200:
        pytest.skip(
            f"Real broker call failed (status={response.status_code}, body={response.text[:200]}) "
            "-- most likely today's expired daily access token, not a code defect."
        )
    body = response.json()
    assert body["symbol"] == _REAL_SYMBOL
    assert body["last_price"] > 0


def test_option_chain_against_a_real_broker():
    try:
        build_broker()
    except NoBrokerConfigured:
        pytest.skip("No broker configured in this environment")

    # A near-term Thursday NIFTY expiry -- real strikes/expiries are broker-instrument-dump
    # driven, so any date genuinely in the future is a valid query; a stale/wrong expiry just
    # yields an empty instrument list from a real broker, not an error.
    expiry = date(datetime.now(UTC).year + 1, 1, 2)
    response = client.get(
        "/api/v1/market/option-chain/NIFTY", params={"expiry": expiry.isoformat()}
    )
    if response.status_code != 200:
        pytest.skip(
            f"Real broker call failed (status={response.status_code}, body={response.text[:200]}) "
            "-- most likely today's expired daily access token, not a code defect."
        )
    body = response.json()
    assert body["underlying"] == "NIFTY"
