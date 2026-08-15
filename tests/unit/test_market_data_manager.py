"""MarketDataManager failover unit tests (REL-070) -- every scenario from the spec's own §32
failover table, exercised against fake in-process providers (no real HTTP/yfinance calls; that's
covered separately by test_upstox_v3_provider.py/test_yahoo_finance_provider.py). This file
proves the *orchestration* logic: which provider gets tried, in what order, with how many
retries, and what real error surfaces when everything fails.
"""

from datetime import date

import pytest

from src.data.providers.base import (
    Candle,
    MarketDataProvider,
    ProviderInstrumentNotFoundError,
    ProviderTimeoutError,
    ProviderTokenExpiredError,
    Timeframe,
)
from src.data.providers.manager import MarketDataManager, MarketDataUnavailable

_DAY = date(2026, 8, 1)


def _candle(provider: str, *, close: float = 100.0) -> Candle:
    from datetime import UTC, datetime

    return Candle(
        timestamp=datetime(2026, 8, 1, tzinfo=UTC),
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000,
        open_interest=None,
        instrument_key="TEST",
        symbol="TEST",
        timeframe="1d",
        provider=provider,
    )


class _FakeProvider(MarketDataProvider):
    def __init__(
        self,
        name: str,
        *,
        healthy: bool = True,
        candles: list[Candle] | None = None,
        raises: Exception | list[Exception] | None = None,
    ) -> None:
        self.name = name
        self._healthy = healthy
        self._candles = candles if candles is not None else [_candle(name)]
        self._raises = raises
        self.call_count = 0
        self.health_check_count = 0

    def get_historical_data(
        self, *, instrument_key: str, symbol: str, start: date, end: date, timeframe: Timeframe
    ) -> list[Candle]:
        self.call_count += 1
        if isinstance(self._raises, list):
            if self.call_count <= len(self._raises):
                raise self._raises[self.call_count - 1]
            return self._candles
        if self._raises is not None:
            raise self._raises
        return self._candles

    def get_latest_data(self, *, instrument_key: str, symbol: str) -> Candle | None:
        return None

    def health_check(self) -> bool:
        self.health_check_count += 1
        return self._healthy


def _manager(*providers: MarketDataProvider, **kwargs: object) -> MarketDataManager:
    return MarketDataManager(list(providers), **kwargs)  # type: ignore[arg-type]


def test_primary_success_never_calls_fallback():
    primary = _FakeProvider("primary")
    fallback = _FakeProvider("fallback")
    result = _manager(primary, fallback).get_historical_data(
        instrument_key="X", symbol="X", start=_DAY, end=_DAY, timeframe="1d"
    )
    assert result.provider_used == "primary"
    assert result.provider_requested == "primary"
    assert fallback.call_count == 0


def test_instrument_not_found_falls_over_immediately_without_retry():
    primary = _FakeProvider("primary", raises=ProviderInstrumentNotFoundError("no such instrument"))
    fallback = _FakeProvider("fallback")
    result = _manager(primary, fallback, max_retries=3).get_historical_data(
        instrument_key="X", symbol="X", start=_DAY, end=_DAY, timeframe="1d"
    )
    assert result.provider_used == "fallback"
    assert primary.call_count == 1  # no retry for a non-retryable error


def test_token_expired_falls_over_immediately():
    primary = _FakeProvider("primary", raises=ProviderTokenExpiredError("expired"))
    fallback = _FakeProvider("fallback")
    result = _manager(primary, fallback, max_retries=3).get_historical_data(
        instrument_key="X", symbol="X", start=_DAY, end=_DAY, timeframe="1d"
    )
    assert result.provider_used == "fallback"
    assert primary.call_count == 1


def test_timeout_retries_then_falls_over():
    primary = _FakeProvider(
        "primary",
        raises=[ProviderTimeoutError("t1"), ProviderTimeoutError("t2"), ProviderTimeoutError("t3")],
    )
    fallback = _FakeProvider("fallback")
    result = _manager(primary, fallback, max_retries=3, backoff_factor=0.0).get_historical_data(
        instrument_key="X", symbol="X", start=_DAY, end=_DAY, timeframe="1d"
    )
    assert result.provider_used == "fallback"
    assert primary.call_count == 3  # exhausted all 3 retries before falling over


def test_timeout_recovers_on_retry_without_falling_over():
    primary = _FakeProvider("primary", raises=[ProviderTimeoutError("t1")])
    fallback = _FakeProvider("fallback")
    result = _manager(primary, fallback, max_retries=3, backoff_factor=0.0).get_historical_data(
        instrument_key="X", symbol="X", start=_DAY, end=_DAY, timeframe="1d"
    )
    assert result.provider_used == "primary"
    assert primary.call_count == 2  # failed once, succeeded on the 2nd attempt
    assert fallback.call_count == 0


def test_unhealthy_provider_is_skipped_without_calling_get_historical_data():
    primary = _FakeProvider("primary", healthy=False)
    fallback = _FakeProvider("fallback")
    result = _manager(primary, fallback).get_historical_data(
        instrument_key="X", symbol="X", start=_DAY, end=_DAY, timeframe="1d"
    )
    assert result.provider_used == "fallback"
    assert primary.call_count == 0
    assert primary.health_check_count == 1


def test_invalid_ohlc_data_is_treated_as_a_provider_failure():
    bad_candle = _candle("primary")
    bad_candle = Candle(
        timestamp=bad_candle.timestamp,
        open=100.0,
        high=90.0,  # high < open -- invalid
        low=80.0,
        close=100.0,
        volume=1000,
        open_interest=None,
        instrument_key="X",
        symbol="X",
        timeframe="1d",
        provider="primary",
    )
    primary = _FakeProvider("primary", candles=[bad_candle])
    fallback = _FakeProvider("fallback")
    result = _manager(primary, fallback).get_historical_data(
        instrument_key="X", symbol="X", start=_DAY, end=_DAY, timeframe="1d"
    )
    assert result.provider_used == "fallback"


def test_both_providers_failing_raises_market_data_unavailable_with_real_reasons():
    primary = _FakeProvider("primary", raises=ProviderInstrumentNotFoundError("no data"))
    fallback = _FakeProvider("fallback", raises=ProviderInstrumentNotFoundError("no data either"))
    with pytest.raises(MarketDataUnavailable) as exc_info:
        _manager(primary, fallback).get_historical_data(
            instrument_key="X", symbol="X", start=_DAY, end=_DAY, timeframe="1d"
        )
    assert "primary" in exc_info.value.errors
    assert "fallback" in exc_info.value.errors


def test_failover_disabled_only_tries_primary():
    primary = _FakeProvider("primary", raises=ProviderInstrumentNotFoundError("no data"))
    fallback = _FakeProvider("fallback")
    with pytest.raises(MarketDataUnavailable) as exc_info:
        _manager(primary, fallback, enable_failover=False).get_historical_data(
            instrument_key="X", symbol="X", start=_DAY, end=_DAY, timeframe="1d"
        )
    assert fallback.call_count == 0
    assert list(exc_info.value.errors) == ["primary"]


def test_per_instrument_isolation_a_primary_failure_does_not_persist_across_calls():
    """A real Upstox rejection for one symbol must not disable Upstox for every other symbol in
    the same run -- each get_historical_data call re-evaluates the primary fresh."""
    primary = _FakeProvider("primary", raises=[ProviderInstrumentNotFoundError("no data for A")])
    fallback = _FakeProvider("fallback")
    manager = _manager(primary, fallback)

    result_a = manager.get_historical_data(
        instrument_key="A", symbol="A", start=_DAY, end=_DAY, timeframe="1d"
    )
    assert result_a.provider_used == "fallback"

    # Primary's raises list is exhausted -- the next real call succeeds again, proving no
    # provider-wide "Upstox is down" latch was set by the first symbol's failure.
    result_b = manager.get_historical_data(
        instrument_key="B", symbol="B", start=_DAY, end=_DAY, timeframe="1d"
    )
    assert result_b.provider_used == "primary"


def test_no_providers_raises_value_error():
    with pytest.raises(ValueError):
        MarketDataManager([])
