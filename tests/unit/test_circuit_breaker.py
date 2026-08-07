"""BrokerCircuitBreaker tests (Phase 4 Epic E4.1), per Phase_6_Trading_Engine_Design.md §6:
consecutive-5XX detection, automated failover, and queue-and-alert when no fallback exists.
"""

import asyncio
import contextlib
from datetime import timedelta

import httpx
import pytest

from src.brokers.base import (
    BrokerAdapter,
    Margin,
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

    def __init__(self, place_order_results: list) -> None:
        self._results = list(place_order_results)
        self.calls = 0

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
        raise NotImplementedError

    async def get_option_chain(self, underlying: str, expiry):
        raise NotImplementedError

    async def list_expiries(self, underlying: str):
        raise NotImplementedError


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
    breaker = BrokerCircuitBreaker(primary=primary, fallback=fallback, failure_threshold=3)

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
    breaker = BrokerCircuitBreaker(primary=primary, fallback=None, failure_threshold=3)

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
    breaker = BrokerCircuitBreaker(primary=primary, fallback=fallback, failure_threshold=3)

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
        primary=primary, failure_threshold=3, cooldown=timedelta(milliseconds=10)
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
        primary=primary, failure_threshold=3, cooldown=timedelta(milliseconds=10)
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
async def test_modify_cancel_and_read_methods_always_target_primary():
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
