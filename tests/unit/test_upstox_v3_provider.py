"""UpstoxV3Provider unit tests (REL-070). Every HTTP call is mocked via `httpx.MockTransport`,
matching tests/unit/test_upstox_adapter.py's own established pattern -- no real network call.
Error-envelope shapes and error codes mirror the real, live-documented Upstox V3 API (see
src/data/providers/upstox_v3.py's own module docstring), not invented ones.
"""

from datetime import date

import httpx
import pytest

from src.data.providers.base import (
    ProviderEmptyDataError,
    ProviderInstrumentNotFoundError,
    ProviderRateLimitError,
    ProviderServerError,
    ProviderTokenExpiredError,
    ProviderUnsupportedIntervalError,
)
from src.data.providers.upstox_v3 import UpstoxV3Provider


def _provider_with_transport(handler) -> UpstoxV3Provider:
    provider = UpstoxV3Provider(token="test-token")
    provider._client = httpx.Client(
        base_url=provider._client.base_url,
        headers=provider._client.headers,
        transport=httpx.MockTransport(handler),
    )
    return provider


_REAL_CANDLE_ROW = ["2026-08-01T00:00:00+05:30", 100.0, 105.0, 99.0, 103.0, 15000, None]


def test_get_historical_data_parses_a_valid_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/historical-candle/" in request.url.path
        assert "/days/1/" in request.url.path
        return httpx.Response(
            200, json={"status": "success", "data": {"candles": [_REAL_CANDLE_ROW]}}
        )

    provider = _provider_with_transport(handler)
    candles = provider.get_historical_data(
        instrument_key="NSE_EQ|INE002A01018",
        symbol="RELIANCE",
        start=date(2026, 8, 1),
        end=date(2026, 8, 1),
        timeframe="1d",
    )

    assert len(candles) == 1
    assert candles[0].open == 100.0
    assert candles[0].close == 103.0
    assert candles[0].open_interest is None
    assert candles[0].provider == "upstox_v3"
    assert candles[0].symbol == "RELIANCE"


def test_get_historical_data_sorts_a_descending_provider_response_ascending():
    """REL-078: Upstox's own real API returns newest-first for a multi-day range (confirmed
    empirically this session against a real futures instrument_key) -- the provider must
    normalize to ascending before returning, since validate_candles() (src/data/providers/
    base.py) deliberately never re-sorts on the caller's behalf."""
    descending_rows = [
        ["2026-08-03T00:00:00+05:30", 103.0, 106.0, 102.0, 105.0, 12000, None],
        ["2026-08-02T00:00:00+05:30", 101.0, 104.0, 100.0, 103.0, 11000, None],
        ["2026-08-01T00:00:00+05:30", 100.0, 105.0, 99.0, 103.0, 15000, None],
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "success", "data": {"candles": descending_rows}})

    provider = _provider_with_transport(handler)
    candles = provider.get_historical_data(
        instrument_key="NSE_FO|68797",
        symbol="TCS FUT 29 SEP 26",
        start=date(2026, 8, 1),
        end=date(2026, 8, 3),
        timeframe="1d",
    )

    assert [c.timestamp.date() for c in candles] == [
        date(2026, 8, 1),
        date(2026, 8, 2),
        date(2026, 8, 3),
    ]
    assert candles[0].open == 100.0
    assert candles[-1].open == 103.0


def test_get_historical_data_url_path_order_is_to_date_then_from_date():
    """Confirmed against the live docs: the real path order is to_date THEN from_date -- the
    opposite of this codebase's own date_from/date_to convention everywhere else, easy to get
    backwards."""
    captured_path = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_path["path"] = request.url.path
        return httpx.Response(
            200, json={"status": "success", "data": {"candles": [_REAL_CANDLE_ROW]}}
        )

    provider = _provider_with_transport(handler)
    provider.get_historical_data(
        instrument_key="NSE_EQ|INE002A01018",
        symbol="RELIANCE",
        start=date(2026, 8, 1),
        end=date(2026, 8, 15),
        timeframe="1d",
    )

    assert captured_path["path"].endswith("/2026-08-15/2026-08-01")


def test_unsupported_interval_never_makes_an_http_call():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"status": "success", "data": {"candles": []}})

    provider = _provider_with_transport(handler)
    with pytest.raises(ProviderUnsupportedIntervalError):
        provider.get_historical_data(
            instrument_key="NSE_EQ|INE002A01018",
            symbol="RELIANCE",
            start=date(2026, 8, 1),
            end=date(2026, 8, 1),
            timeframe="3m",  # type: ignore[arg-type]  -- deliberately invalid for this test
        )
    assert calls["n"] == 0


def test_empty_response_raises_empty_data_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "success", "data": {"candles": []}})

    provider = _provider_with_transport(handler)
    with pytest.raises(ProviderEmptyDataError):
        provider.get_historical_data(
            instrument_key="NSE_EQ|INE002A01018",
            symbol="RELIANCE",
            start=date(2026, 8, 1),
            end=date(2026, 8, 1),
            timeframe="1d",
        )


def test_401_raises_token_expired():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"status": "error", "errors": [{"errorCode": "UDAPI1000"}]})

    provider = _provider_with_transport(handler)
    with pytest.raises(ProviderTokenExpiredError):
        provider.get_historical_data(
            instrument_key="NSE_EQ|INE002A01018",
            symbol="RELIANCE",
            start=date(2026, 8, 1),
            end=date(2026, 8, 1),
            timeframe="1d",
        )


def test_429_raises_rate_limit():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"status": "error", "errors": []})

    provider = _provider_with_transport(handler)
    with pytest.raises(ProviderRateLimitError):
        provider.get_historical_data(
            instrument_key="NSE_EQ|INE002A01018",
            symbol="RELIANCE",
            start=date(2026, 8, 1),
            end=date(2026, 8, 1),
            timeframe="1d",
        )


def test_500_raises_server_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"status": "error", "errors": []})

    provider = _provider_with_transport(handler)
    with pytest.raises(ProviderServerError):
        provider.get_historical_data(
            instrument_key="NSE_EQ|INE002A01018",
            symbol="RELIANCE",
            start=date(2026, 8, 1),
            end=date(2026, 8, 1),
            timeframe="1d",
        )


def test_real_udapi_instrument_not_found_code_maps_correctly():
    """Real, documented Upstox error code (confirmed against the live docs), not invented."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "status": "error",
                "errors": [{"errorCode": "UDAPI100011", "message": "Invalid Instrument key"}],
            },
        )

    provider = _provider_with_transport(handler)
    with pytest.raises(ProviderInstrumentNotFoundError):
        provider.get_historical_data(
            instrument_key="NOT-A-REAL-KEY",
            symbol="RELIANCE",
            start=date(2026, 8, 1),
            end=date(2026, 8, 1),
            timeframe="1d",
        )


def test_health_check_returns_true_on_success():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"status": "success", "data": {"candles": [_REAL_CANDLE_ROW]}}
        )

    provider = _provider_with_transport(handler)
    assert provider.health_check() is True


def test_health_check_returns_false_on_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"status": "error", "errors": [{"errorCode": "UDAPI1000"}]})

    provider = _provider_with_transport(handler)
    assert provider.health_check() is False
