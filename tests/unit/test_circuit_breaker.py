"""BrokerCircuitBreaker tests (Phase 4 Epic E4.1), per Phase_6_Trading_Engine_Design.md §6:
consecutive-5XX detection, automated failover, and queue-and-alert when no fallback exists.
"""

import asyncio
import contextlib
from datetime import date, timedelta

import httpx
import pytest

from src.brokers.base import (
    BrokerAdapter,
    Margin,
    OptionChain,
    OrderRequest,
    OrderResponse,
    OrderType,
    Position,
    Quote,
)
from src.brokers.circuit_breaker import AdminAlert, BrokerCircuitBreaker


class FakeBrokerAdapter(BrokerAdapter):
    """A scripted test double: `place_order_results` is consumed one at a time, each entry
    either an `OrderResponse` (success) or an `Exception` instance (raised)."""

    def __init__(
        self,
        place_order_results: list,
        *,
        quote_result: object = None,
        chain_result: object = None,
        expiries_result: object = None,
    ) -> None:
        self._results = list(place_order_results)
        self.calls = 0
        # Each of these is either a value (returned) or an `Exception` instance (raised) --
        # mirrors the place_order_results convention above, for the market-data failover tests.
        self._quote_result = quote_result
        self._chain_result = chain_result
        self._expiries_result = expiries_result
        self.quote_calls = 0
        self.chain_calls = 0
        self.expiries_calls = 0

    async def place_order(self, order: OrderRequest) -> OrderResponse:
        self.calls += 1
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def modify_order(
        self,
        broker_order_id: str,
        *,
        quantity: int | None = None,
        order_type: OrderType | None = None,
        limit_price: float | None = None,
        trigger_price: float | None = None,
    ) -> OrderResponse:
        return _dummy_response(broker_order_id)

    async def cancel_order(self, broker_order_id: str) -> OrderResponse:
        return _dummy_response(broker_order_id)

    async def get_order_book(self) -> list[OrderResponse]:
        return []

    async def get_margin(self) -> Margin:
        return Margin(available_margin=0.0, used_margin=0.0)

    async def get_positions(self) -> list[Position]:
        return []

    async def get_quote(self, symbol: str) -> Quote:
        self.quote_calls += 1
        if self._quote_result is None:
            raise NotImplementedError
        if isinstance(self._quote_result, Exception):
            raise self._quote_result
        return self._quote_result

    async def get_option_chain(self, underlying: str, expiry):
        self.chain_calls += 1
        if self._chain_result is None:
            raise NotImplementedError
        if isinstance(self._chain_result, Exception):
            raise self._chain_result
        return self._chain_result

    async def list_expiries(self, underlying: str):
        self.expiries_calls += 1
        if self._expiries_result is None:
            raise NotImplementedError
        if isinstance(self._expiries_result, Exception):
            raise self._expiries_result
        return self._expiries_result


def _dummy_response(broker_order_id: str = "X") -> OrderResponse:
    return OrderResponse(
        broker_order_id=broker_order_id,
        status="OPEN",
        symbol="RELIANCE",
        side="BUY",
        order_type="MARKET",
        quantity=1,
    )


def _order() -> OrderRequest:
    return OrderRequest(symbol="RELIANCE", side="BUY", order_type="MARKET", quantity=1)


def _server_error(status_code: int = 503) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://example.com/order/place")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError("server error", request=request, response=response)


def _forbidden() -> httpx.HTTPStatusError:
    """The real failure mode this fail-over exists for: Zerodha's daily-expiring Kite Connect
    access token returns 403 on every call once it lapses (~6 AM IST, no refresh token, GLH-11)."""
    request = httpx.Request("GET", "https://api.kite.trade/quote")
    response = httpx.Response(403, request=request)
    return httpx.HTTPStatusError("forbidden", request=request, response=response)


def _quote(last_price: float = 1289.0) -> Quote:
    return Quote(symbol="RELIANCE", last_price=last_price)


def _no_alert_transport() -> httpx.MockTransport:
    """Every test below that trips the circuit breaker also fires a real `_alert()` call, which
    now sends via `src.core.ops_alerts.send_ops_alert` (Phase 4 E4.4) -- this dev `.env` has real
    Slack/Telegram/Discord webhook credentials configured, so without this mock a plain unit-test
    run would post real messages to those real channels. Matches the `httpx.MockTransport`
    convention already established in test_ops_alerts.py."""
    return httpx.MockTransport(lambda request: httpx.Response(202))


@pytest.mark.asyncio
async def test_closed_circuit_routes_to_primary_on_success():
    primary = FakeBrokerAdapter([_dummy_response("P1")])
    breaker = BrokerCircuitBreaker(primary=primary)

    result = await breaker.place_order(_order())

    assert result.broker_order_id == "P1"
    assert breaker.state == "CLOSED"


@pytest.mark.asyncio
async def test_failures_below_threshold_propagate_without_opening_the_circuit():
    primary = FakeBrokerAdapter([_server_error(), _server_error()])
    breaker = BrokerCircuitBreaker(primary=primary, failure_threshold=3)

    with pytest.raises(httpx.HTTPStatusError):
        await breaker.place_order(_order())
    with pytest.raises(httpx.HTTPStatusError):
        await breaker.place_order(_order())

    assert breaker.state == "CLOSED"


@pytest.mark.asyncio
async def test_a_non_5xx_error_never_trips_the_circuit():
    request = httpx.Request("POST", "https://example.com/order/place")
    bad_request = httpx.HTTPStatusError(
        "bad request", request=request, response=httpx.Response(400, request=request)
    )
    primary = FakeBrokerAdapter([bad_request] * 10)
    breaker = BrokerCircuitBreaker(primary=primary, failure_threshold=3)

    for _ in range(10):
        with pytest.raises(httpx.HTTPStatusError):
            await breaker.place_order(_order())

    assert breaker.state == "CLOSED"


@pytest.mark.asyncio
async def test_consecutive_5xx_at_threshold_opens_circuit_and_fails_over():
    primary = FakeBrokerAdapter([_server_error(), _server_error(), _server_error()])
    fallback = FakeBrokerAdapter([_dummy_response("F1")])
    breaker = BrokerCircuitBreaker(
        primary=primary,
        fallback=fallback,
        failure_threshold=3,
        alert_transport=_no_alert_transport(),
    )

    with pytest.raises(httpx.HTTPStatusError):
        await breaker.place_order(_order())
    with pytest.raises(httpx.HTTPStatusError):
        await breaker.place_order(_order())
    result = await breaker.place_order(_order())  # 3rd failure trips the circuit and fails over

    assert breaker.state == "OPEN"
    assert result.broker_order_id == "F1"
    assert len(breaker.alerts) == 1


@pytest.mark.asyncio
async def test_open_circuit_with_no_fallback_queues_the_order_and_raises_admin_alert():
    primary = FakeBrokerAdapter([_server_error()] * 3)
    breaker = BrokerCircuitBreaker(
        primary=primary, fallback=None, failure_threshold=3, alert_transport=_no_alert_transport()
    )

    with pytest.raises(httpx.HTTPStatusError):
        await breaker.place_order(_order())
    with pytest.raises(httpx.HTTPStatusError):
        await breaker.place_order(_order())
    with pytest.raises(AdminAlert):
        await breaker.place_order(_order())

    assert breaker.state == "OPEN"
    assert len(breaker.queued_orders) == 1
    assert breaker.queued_orders[0].order.symbol == "RELIANCE"


@pytest.mark.asyncio
async def test_open_circuit_routes_subsequent_orders_straight_to_fallback():
    primary = FakeBrokerAdapter([_server_error(), _server_error(), _server_error()])
    fallback = FakeBrokerAdapter([_dummy_response("F1"), _dummy_response("F2")])
    breaker = BrokerCircuitBreaker(
        primary=primary,
        fallback=fallback,
        failure_threshold=3,
        alert_transport=_no_alert_transport(),
    )

    for _ in range(3):
        with contextlib.suppress(httpx.HTTPStatusError):
            await breaker.place_order(_order())

    assert breaker.state == "OPEN"
    result = await breaker.place_order(_order())  # circuit already open -- straight to fallback

    assert result.broker_order_id == "F2"
    assert primary.calls == 3  # not called again while open


@pytest.mark.asyncio
async def test_half_open_after_cooldown_recovers_to_closed_on_success():
    primary = FakeBrokerAdapter(
        [_server_error(), _server_error(), _server_error(), _dummy_response("RECOVERED")]
    )
    breaker = BrokerCircuitBreaker(
        primary=primary,
        failure_threshold=3,
        cooldown=timedelta(milliseconds=10),
        alert_transport=_no_alert_transport(),
    )

    for _ in range(3):
        with contextlib.suppress(httpx.HTTPStatusError, AdminAlert):
            await breaker.place_order(_order())
    assert breaker.state == "OPEN"

    await asyncio.sleep(0.05)  # let the cooldown elapse
    result = await breaker.place_order(_order())

    assert result.broker_order_id == "RECOVERED"
    assert breaker.state == "CLOSED"


@pytest.mark.asyncio
async def test_half_open_probe_failure_reopens_immediately_without_a_fallback():
    primary = FakeBrokerAdapter(
        [_server_error(), _server_error(), _server_error(), _server_error()]
    )
    breaker = BrokerCircuitBreaker(
        primary=primary,
        failure_threshold=3,
        cooldown=timedelta(milliseconds=10),
        alert_transport=_no_alert_transport(),
    )

    for _ in range(3):
        with contextlib.suppress(httpx.HTTPStatusError, AdminAlert):
            await breaker.place_order(_order())
    assert breaker.state == "OPEN"

    await asyncio.sleep(0.05)
    with pytest.raises(AdminAlert):
        await breaker.place_order(_order())  # single probe failure, not 3 more

    assert breaker.state == "OPEN"


@pytest.mark.asyncio
async def test_a_success_resets_the_consecutive_failure_counter():
    primary = FakeBrokerAdapter(
        [_server_error(), _server_error(), _dummy_response("OK"), _server_error(), _server_error()]
    )
    breaker = BrokerCircuitBreaker(primary=primary, failure_threshold=3)

    for _ in range(2):
        with pytest.raises(httpx.HTTPStatusError):
            await breaker.place_order(_order())
    await breaker.place_order(_order())  # success resets the counter
    for _ in range(2):
        with pytest.raises(httpx.HTTPStatusError):
            await breaker.place_order(_order())

    # 2 failures + reset + 2 failures = never reached the threshold of 3 in a row.
    assert breaker.state == "CLOSED"


@pytest.mark.asyncio
async def test_modify_cancel_and_account_state_reads_always_target_primary():
    primary = FakeBrokerAdapter([])
    fallback = FakeBrokerAdapter([])
    breaker = BrokerCircuitBreaker(primary=primary, fallback=fallback)

    await breaker.modify_order("ORD1", quantity=5)
    await breaker.cancel_order("ORD1")
    await breaker.get_order_book()
    await breaker.get_margin()
    await breaker.get_positions()

    # None of these touched place_order's failure-counting machinery.
    assert breaker.state == "CLOSED"


@pytest.mark.asyncio
async def test_get_quote_fails_over_to_fallback_when_primary_is_unreachable():
    """The real GLH-11 scenario: Zerodha's daily token has lapsed (403 on every call), but
    Upstox's token is still valid -- the live tick feed must keep flowing off Upstox, not go
    dark. A quote is broker-agnostic, so unlike the account-state reads this one fails over."""
    primary = FakeBrokerAdapter([], quote_result=_forbidden())
    fallback = FakeBrokerAdapter([], quote_result=_quote(1289.0))
    breaker = BrokerCircuitBreaker(primary=primary, fallback=fallback)

    quote = await breaker.get_quote("RELIANCE")

    assert quote.last_price == 1289.0
    assert primary.quote_calls == 1
    assert fallback.quote_calls == 1
    assert breaker.state == "CLOSED"  # a read failover never touches circuit state


@pytest.mark.asyncio
async def test_get_quote_propagates_the_error_when_there_is_no_fallback():
    primary = FakeBrokerAdapter([], quote_result=_forbidden())
    breaker = BrokerCircuitBreaker(primary=primary, fallback=None)

    with pytest.raises(httpx.HTTPStatusError):
        await breaker.get_quote("RELIANCE")


@pytest.mark.asyncio
async def test_get_quote_uses_primary_when_it_is_healthy():
    primary = FakeBrokerAdapter([], quote_result=_quote(1300.0))
    fallback = FakeBrokerAdapter([], quote_result=_quote(999.0))
    breaker = BrokerCircuitBreaker(primary=primary, fallback=fallback)

    quote = await breaker.get_quote("RELIANCE")

    assert quote.last_price == 1300.0
    assert fallback.quote_calls == 0


def _chain(spot: float = 24500.0) -> OptionChain:
    return OptionChain(underlying="NIFTY", expiry=date(2026, 9, 15), spot_price=spot)


@pytest.mark.asyncio
async def test_get_option_chain_fails_over_to_fallback_when_primary_is_unreachable():
    """The exact symptom a user hit: the Options Chain browser 502'd because the Zerodha daily
    token had lapsed (`/quote?i=NSE:NIFTY 50` -> 403), even though Upstox's token was valid. An
    option chain is broker-agnostic market data, so it fails over just like get_quote."""
    primary = FakeBrokerAdapter([], chain_result=_forbidden())
    fallback = FakeBrokerAdapter([], chain_result=_chain(24500.0))
    breaker = BrokerCircuitBreaker(primary=primary, fallback=fallback)

    chain = await breaker.get_option_chain("NIFTY", date(2026, 9, 15))

    assert chain.spot_price == 24500.0
    assert primary.chain_calls == 1
    assert fallback.chain_calls == 1
    assert breaker.state == "CLOSED"


@pytest.mark.asyncio
async def test_list_expiries_fails_over_to_fallback_when_primary_is_unreachable():
    primary = FakeBrokerAdapter([], expiries_result=_forbidden())
    fallback = FakeBrokerAdapter([], expiries_result=[date(2026, 9, 15), date(2026, 9, 22)])
    breaker = BrokerCircuitBreaker(primary=primary, fallback=fallback)

    expiries = await breaker.list_expiries("NIFTY")

    assert expiries == [date(2026, 9, 15), date(2026, 9, 22)]
    assert fallback.expiries_calls == 1


@pytest.mark.asyncio
async def test_option_chain_and_expiries_propagate_when_there_is_no_fallback():
    primary = FakeBrokerAdapter([], chain_result=_forbidden(), expiries_result=_forbidden())
    breaker = BrokerCircuitBreaker(primary=primary, fallback=None)

    with pytest.raises(httpx.HTTPStatusError):
        await breaker.get_option_chain("NIFTY", date(2026, 9, 15))
    with pytest.raises(httpx.HTTPStatusError):
        await breaker.list_expiries("NIFTY")
