"""UpstoxAdapter unit tests (Phase 4 Epic E4.1): every Upstox HTTP call is mocked via
`httpx.MockTransport` -- these tests verify our request/response mapping logic and must never
make a real network call, let alone place a real order.
"""

import httpx
import pytest

from src.brokers.base import OrderRequest
from src.brokers.upstox_adapter import (
    UPSTOX_PRODUCTION_BASE_URL,
    UPSTOX_SANDBOX_BASE_URL,
    UpstoxAdapter,
    UpstoxOrderStatusError,
)


def _adapter_with_transport(handler, *, use_sandbox: bool = True) -> UpstoxAdapter:
    adapter = UpstoxAdapter(access_token="test-token", use_sandbox=use_sandbox)
    adapter._client = httpx.AsyncClient(
        base_url=adapter._client.base_url,
        headers=adapter._client.headers,
        transport=httpx.MockTransport(handler),
    )
    return adapter


def test_sandbox_is_the_default_base_url():
    adapter = UpstoxAdapter(access_token="test-token")
    assert str(adapter._client.base_url) == UPSTOX_SANDBOX_BASE_URL + "/"


def test_production_base_url_requires_an_explicit_opt_out_of_sandbox():
    adapter = UpstoxAdapter(access_token="test-token", use_sandbox=False)
    assert str(adapter._client.base_url) == UPSTOX_PRODUCTION_BASE_URL + "/"


@pytest.mark.asyncio
async def test_place_order_builds_the_correct_payload_and_parses_the_response():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"status": "success", "data": {"order_id": "ORD123"}})

    adapter = _adapter_with_transport(handler)
    order = OrderRequest(
        symbol="NSE_EQ|INE002A01018",
        side="BUY",
        order_type="LIMIT",
        quantity=10,
        product="INTRADAY",
        limit_price=2500.0,
    )

    result = await adapter.place_order(order)

    assert captured["method"] == "POST"
    assert captured["url"].endswith("/order/place")
    assert result.broker_order_id == "ORD123"
    assert result.status == "PENDING"
    assert result.symbol == "NSE_EQ|INE002A01018"
    assert result.quantity == 10


@pytest.mark.asyncio
async def test_modify_order_refetches_the_order_book_for_the_real_current_state():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            return httpx.Response(200, json={"status": "success", "data": {"order_id": "ORD1"}})
        assert request.url.path.endswith("/order/retrieve-all")
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": [
                    {
                        "order_id": "ORD1",
                        "status": "open",
                        "trading_symbol": "RELIANCE",
                        "transaction_type": "BUY",
                        "order_type": "LIMIT",
                        "quantity": 15,
                        "filled_quantity": 0,
                        "average_price": 0,
                        "price": 2600.0,
                        "status_message": None,
                    }
                ],
            },
        )

    adapter = _adapter_with_transport(handler)
    result = await adapter.modify_order("ORD1", quantity=15, limit_price=2600.0)

    assert result.status == "OPEN"
    assert result.quantity == 15
    assert result.limit_price == 2600.0


@pytest.mark.asyncio
async def test_cancel_order_returns_the_real_post_cancel_state_not_an_assumed_one():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            assert request.url.params["order_id"] == "ORD1"
            return httpx.Response(200, json={"status": "success", "data": {"order_id": "ORD1"}})
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": [
                    {
                        "order_id": "ORD1",
                        # A fill raced the cancel -- this is exactly why we re-fetch instead of
                        # assuming "CANCELLED".
                        "status": "complete",
                        "trading_symbol": "RELIANCE",
                        "transaction_type": "BUY",
                        "order_type": "MARKET",
                        "quantity": 10,
                        "filled_quantity": 10,
                        "average_price": 2505.5,
                        "price": 0,
                        "status_message": None,
                    }
                ],
            },
        )

    adapter = _adapter_with_transport(handler)
    result = await adapter.cancel_order("ORD1")

    assert result.status == "FILLED"
    assert result.filled_quantity == 10


@pytest.mark.asyncio
async def test_get_order_book_parses_multiple_statuses():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": [
                    {
                        "order_id": "A",
                        "status": "complete",
                        "trading_symbol": "RELIANCE",
                        "transaction_type": "BUY",
                        "order_type": "MARKET",
                        "quantity": 5,
                        "filled_quantity": 5,
                        "average_price": 100.0,
                        "price": 0,
                        "status_message": None,
                    },
                    {
                        "order_id": "B",
                        "status": "rejected",
                        "trading_symbol": "TCS",
                        "transaction_type": "SELL",
                        "order_type": "LIMIT",
                        "quantity": 3,
                        "filled_quantity": 0,
                        "average_price": 0,
                        "price": 3500.0,
                        "status_message": "insufficient margin",
                    },
                ],
            },
        )

    adapter = _adapter_with_transport(handler)
    orders = await adapter.get_order_book()

    assert len(orders) == 2
    assert orders[0].status == "FILLED"
    assert orders[1].status == "REJECTED"
    assert orders[1].rejection_reason == "insufficient margin"


@pytest.mark.asyncio
async def test_get_order_book_raises_on_an_unmapped_status():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": [
                    {
                        "order_id": "X",
                        "status": "some-new-status-upstox-added-later",
                        "trading_symbol": "RELIANCE",
                        "transaction_type": "BUY",
                        "order_type": "MARKET",
                        "quantity": 1,
                        "filled_quantity": 0,
                        "average_price": 0,
                        "price": 0,
                        "status_message": None,
                    }
                ],
            },
        )

    adapter = _adapter_with_transport(handler)
    with pytest.raises(UpstoxOrderStatusError):
        await adapter.get_order_book()


@pytest.mark.asyncio
async def test_get_margin_maps_the_documented_fields():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["segment"] == "SEC"
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "used_margin": 1000.0,
                    "payin_amount": 0.0,
                    "span_margin": 0.0,
                    "adhoc_margin": 0.0,
                    "notional_cash": 0.0,
                    "available_margin": 50000.0,
                    "exposure_margin": 0.0,
                },
            },
        )

    adapter = _adapter_with_transport(handler)
    margin = await adapter.get_margin()

    assert margin.available_margin == 50000.0
    assert margin.used_margin == 1000.0


@pytest.mark.asyncio
async def test_get_positions_maps_the_documented_fields():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": [
                    {
                        "trading_symbol": "RELIANCE",
                        "instrument_token": "NSE_EQ|INE002A01018",
                        "quantity": 10,
                        "average_price": 2500.0,
                        "last_price": 2550.0,
                        "unrealised": 500.0,
                        "realised": 0.0,
                    }
                ],
            },
        )

    adapter = _adapter_with_transport(handler)
    positions = await adapter.get_positions()

    assert len(positions) == 1
    assert positions[0].symbol == "RELIANCE"
    assert positions[0].net_quantity == 10
    assert positions[0].unrealized_pnl == 500.0


@pytest.mark.asyncio
async def test_search_instrument_key_returns_the_first_match():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["query"] == "RELIANCE"
        return httpx.Response(
            200,
            json={"status": "success", "data": [{"instrument_key": "NSE_EQ|INE002A01018"}]},
        )

    adapter = _adapter_with_transport(handler)
    instrument_key = await adapter.search_instrument_key("RELIANCE")

    assert instrument_key == "NSE_EQ|INE002A01018"


@pytest.mark.asyncio
async def test_search_instrument_key_raises_when_nothing_matches():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "success", "data": []})

    adapter = _adapter_with_transport(handler)
    with pytest.raises(ValueError, match="No Upstox instrument found"):
        await adapter.search_instrument_key("NOT-A-REAL-SYMBOL")


@pytest.mark.asyncio
async def test_get_quote_always_hits_production_even_in_sandbox_mode():
    """Field shape confirmed live against Upstox's own docs this session
    (https://upstox.com/developer/api-documentation/get-full-market-quote/): GET
    /market-quote/quotes?instrument_key=..., response keyed by "EXCHANGE:SYMBOL". This endpoint
    has no sandbox host at all -- must be reachable even when the adapter is constructed with
    use_sandbox=True (the safe default for order placement)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/instruments/search"):
            return httpx.Response(
                200,
                json={"status": "success", "data": [{"instrument_key": "NSE_EQ|INE009A01021"}]},
            )
        assert str(request.url).startswith(UPSTOX_PRODUCTION_BASE_URL)
        assert request.url.params["instrument_key"] == "NSE_EQ|INE009A01021"
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "NSE_EQ:INFY": {
                        "last_price": 1412.95,
                        "depth": {
                            "buy": [{"price": 1412.50, "quantity": 100, "orders": 3}],
                            "sell": [{"price": 1412.95, "quantity": 5191, "orders": 13}],
                        },
                    }
                },
            },
        )

    adapter = _adapter_with_transport(handler, use_sandbox=True)
    quote = await adapter.get_quote("INFY")

    assert quote.symbol == "INFY"
    assert quote.last_price == 1412.95
    assert quote.buy_depth[0].quantity == 100
    assert quote.sell_depth[0].orders == 13
