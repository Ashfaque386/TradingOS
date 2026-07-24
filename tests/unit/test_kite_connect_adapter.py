"""KiteConnectAdapter unit tests (Phase 4 Epic E4.1): every Kite HTTP call is mocked via
`httpx.MockTransport` -- these tests verify our request/response mapping logic and must NEVER
make a real network call. Kite Connect has no sandbox mode; place_order/modify_order/
cancel_order are exercised ONLY here, never against the live API (see
tests/integration/test_kite_connect_live.py, which covers only read-only endpoints).
"""

import httpx
import pytest

from src.brokers.base import OrderRequest
from src.brokers.kite_connect_adapter import KiteConnectAdapter, KiteOrderStatusError


def _adapter_with_transport(handler) -> KiteConnectAdapter:
    adapter = KiteConnectAdapter(api_key="test-key", access_token="test-token")
    adapter._client = httpx.AsyncClient(
        base_url=adapter._client.base_url,
        headers=adapter._client.headers,
        transport=httpx.MockTransport(handler),
    )
    return adapter


@pytest.mark.asyncio
async def test_client_sends_the_correct_auth_and_version_headers():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization")
        captured["x-kite-version"] = request.headers.get("x-kite-version")
        return httpx.Response(200, json={"status": "success", "data": {"net": [], "day": []}})

    adapter = _adapter_with_transport(handler)
    await adapter.get_positions()

    assert captured["authorization"] == "token test-key:test-token"
    assert captured["x-kite-version"] == "3"


@pytest.mark.asyncio
async def test_place_order_posts_to_the_regular_variety_path_and_parses_the_response():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"status": "success", "data": {"order_id": "ORD123"}})

    adapter = _adapter_with_transport(handler)
    order = OrderRequest(
        symbol="RELIANCE",
        side="BUY",
        order_type="LIMIT",
        quantity=10,
        product="INTRADAY",
        limit_price=2500.0,
    )

    result = await adapter.place_order(order)

    assert captured["method"] == "POST"
    assert captured["url"].endswith("/orders/regular")
    assert result.broker_order_id == "ORD123"
    assert result.status == "PENDING"
    assert result.symbol == "RELIANCE"
    assert result.quantity == 10


@pytest.mark.asyncio
async def test_modify_order_refetches_the_order_book_for_the_real_current_state():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            assert request.url.path == "/orders/regular/ORD1"
            return httpx.Response(200, json={"status": "success", "data": {"order_id": "ORD1"}})
        assert request.url.path == "/orders"
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": [
                    {
                        "order_id": "ORD1",
                        "status": "OPEN",
                        "tradingsymbol": "RELIANCE",
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
            assert request.url.path == "/orders/regular/ORD1"
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
                        "status": "COMPLETE",
                        "tradingsymbol": "RELIANCE",
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
                        "status": "COMPLETE",
                        "tradingsymbol": "RELIANCE",
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
                        "status": "REJECTED",
                        "tradingsymbol": "TCS",
                        "transaction_type": "SELL",
                        "order_type": "LIMIT",
                        "quantity": 3,
                        "filled_quantity": 0,
                        "average_price": 0,
                        "price": 3500.0,
                        "status_message": "RMS:Insufficient funds",
                    },
                ],
            },
        )

    adapter = _adapter_with_transport(handler)
    orders = await adapter.get_order_book()

    assert len(orders) == 2
    assert orders[0].status == "FILLED"
    assert orders[1].status == "REJECTED"
    assert orders[1].rejection_reason == "RMS:Insufficient funds"


@pytest.mark.asyncio
async def test_get_order_book_marks_a_partially_filled_open_order_correctly():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": [
                    {
                        "order_id": "A",
                        "status": "OPEN",  # Kite has no distinct partial-fill status string
                        "tradingsymbol": "RELIANCE",
                        "transaction_type": "BUY",
                        "order_type": "LIMIT",
                        "quantity": 10,
                        "filled_quantity": 4,
                        "average_price": 2500.0,
                        "price": 2500.0,
                        "status_message": None,
                    }
                ],
            },
        )

    adapter = _adapter_with_transport(handler)
    orders = await adapter.get_order_book()

    assert orders[0].status == "PARTIALLY_FILLED"
    assert orders[0].filled_quantity == 4


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
                        "status": "some-new-status-kite-added-later",
                        "tradingsymbol": "RELIANCE",
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
    with pytest.raises(KiteOrderStatusError):
        await adapter.get_order_book()


@pytest.mark.asyncio
async def test_get_margin_maps_the_documented_fields():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/user/margins/equity"
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "enabled": True,
                    "net": 50000.0,
                    "available": {"cash": 50000.0},
                    "utilised": {"debits": 1000.0},
                },
            },
        )

    adapter = _adapter_with_transport(handler)
    margin = await adapter.get_margin()

    assert margin.available_margin == 50000.0
    assert margin.used_margin == 1000.0


@pytest.mark.asyncio
async def test_get_positions_maps_only_net_positions():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "net": [
                        {
                            "tradingsymbol": "RELIANCE",
                            "quantity": 10,
                            "average_price": 2500.0,
                            "last_price": 2550.0,
                            "unrealised": 500.0,
                            "realised": 0.0,
                        }
                    ],
                    "day": [
                        {
                            "tradingsymbol": "RELIANCE",
                            "quantity": 10,
                            "average_price": 2500.0,
                            "last_price": 2550.0,
                            "unrealised": 500.0,
                            "realised": 0.0,
                        }
                    ],
                },
            },
        )

    adapter = _adapter_with_transport(handler)
    positions = await adapter.get_positions()

    assert len(positions) == 1
    assert positions[0].symbol == "RELIANCE"
    assert positions[0].net_quantity == 10
    assert positions[0].unrealized_pnl == 500.0


@pytest.mark.asyncio
async def test_get_quote_maps_the_real_depth_shape():
    """Field shape confirmed live against Kite Connect's own docs this session
    (https://kite.trade/docs/connect/v3/market-quotes/): GET /quote?i=NSE:<symbol>, response
    keyed by "NSE:<symbol>", 5 depth levels each side with {price, quantity, orders}."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/quote"
        assert request.url.params["i"] == "NSE:INFY"
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "NSE:INFY": {
                        "instrument_token": 408065,
                        "last_price": 1412.95,
                        "depth": {
                            "buy": [{"price": 1412.50, "quantity": 100, "orders": 3}],
                            "sell": [{"price": 1412.95, "quantity": 5191, "orders": 13}],
                        },
                    }
                },
            },
        )

    adapter = _adapter_with_transport(handler)
    quote = await adapter.get_quote("INFY")

    assert quote.symbol == "INFY"
    assert quote.last_price == 1412.95
    assert quote.buy_depth[0].price == 1412.50
    assert quote.buy_depth[0].quantity == 100
    assert quote.sell_depth[0].price == 1412.95
    assert quote.sell_depth[0].orders == 13
