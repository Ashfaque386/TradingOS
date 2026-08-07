"""KiteConnectAdapter unit tests (Phase 4 Epic E4.1): every Kite HTTP call is mocked via
`httpx.MockTransport` -- these tests verify our request/response mapping logic and must NEVER
make a real network call. Kite Connect has no sandbox mode; place_order/modify_order/
cancel_order are exercised ONLY here, never against the live API (see
tests/integration/test_kite_connect_live.py, which covers only read-only endpoints).
"""

from datetime import date

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


@pytest.mark.asyncio
async def test_get_option_chain_filters_by_underlying_and_expiry_then_batch_quotes():
    real_csv_header = (
        "instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,"
        "tick_size,lot_size,instrument_type,segment,exchange\n"
    )
    real_csv_rows = (
        # 2 matching rows (same underlying+expiry), 1 non-matching (different expiry)
        "1,1,NIFTY26AUG24000CE,NIFTY,0,2026-08-06,24000,0.05,50,CE,NFO-OPT,NFO\n"
        "2,2,NIFTY26AUG24000PE,NIFTY,0,2026-08-06,24000,0.05,50,PE,NFO-OPT,NFO\n"
        "3,3,NIFTY26SEP24000CE,NIFTY,0,2026-09-24,24000,0.05,50,CE,NFO-OPT,NFO\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/instruments/NFO":
            return httpx.Response(200, text=real_csv_header + real_csv_rows)
        if request.url.path == "/quote":
            requested_keys = request.url.params.get_list("i")
            # REL-030: NIFTY's real Kite tradingsymbol for /quote is "NIFTY 50", not the bare
            # "NIFTY" the NFO instrument dump's own `name` column uses -- a real, confirmed Kite
            # quirk, not test-only fixture noise (see _INDEX_QUOTE_SYMBOLS's own docstring).
            if requested_keys == ["NSE:NIFTY 50"]:
                return httpx.Response(
                    200,
                    json={
                        "status": "success",
                        "data": {"NSE:NIFTY 50": {"last_price": 24100.0, "depth": {}}},
                    },
                )
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": {
                        "NFO:NIFTY26AUG24000CE": {"last_price": 150.0, "oi": 1000},
                        "NFO:NIFTY26AUG24000PE": {"last_price": 120.0, "oi": 900},
                    },
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    adapter = _adapter_with_transport(handler)
    chain = await adapter.get_option_chain("NIFTY", date(2026, 8, 6))

    assert chain.underlying == "NIFTY"
    assert chain.spot_price == 24100.0
    assert len(chain.instruments) == 2  # the Sep-expiry row is correctly excluded
    ce = next(i for i in chain.instruments if i.option_type == "CE")
    assert ce.strike == 24000.0
    assert ce.last_price == 150.0
    assert ce.open_interest == 1000
    assert ce.implied_volatility is not None


@pytest.mark.asyncio
async def test_get_option_chain_maps_a_real_index_underlying_to_its_real_quote_symbol():
    """REL-030: found live, against the real production API, before this fix existed --
    get_option_chain("NIFTY", ...) genuinely 500'd with a real KeyError because Kite's real
    /quote endpoint needs "NIFTY 50", not the bare "NIFTY" the NFO instrument dump's own `name`
    column uses. Covers all 3 real confirmed index mappings, not just NIFTY."""
    real_csv_header = (
        "instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,"
        "tick_size,lot_size,instrument_type,segment,exchange\n"
    )
    real_csv_rows = (
        "1,1,BANKNIFTY26AUG50000CE,BANKNIFTY,0,2026-08-06,50000,0.05,25,CE,NFO-OPT,NFO\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/instruments/NFO":
            return httpx.Response(200, text=real_csv_header + real_csv_rows)
        if request.url.path == "/quote":
            requested_keys = request.url.params.get_list("i")
            if requested_keys[0].startswith("NSE:"):
                assert requested_keys == [
                    "NSE:NIFTY BANK"
                ], f"expected the real mapped index quote symbol, got {requested_keys}"
                return httpx.Response(
                    200,
                    json={
                        "status": "success",
                        "data": {"NSE:NIFTY BANK": {"last_price": 50100.0, "depth": {}}},
                    },
                )
            # the separate batch quote for the option instruments themselves (NFO: keys)
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": {"NFO:BANKNIFTY26AUG50000CE": {"last_price": 800.0, "oi": 500}},
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    adapter = _adapter_with_transport(handler)
    chain = await adapter.get_option_chain("BANKNIFTY", date(2026, 8, 6))

    assert chain.spot_price == 50100.0


@pytest.mark.asyncio
async def test_get_option_chain_uses_a_plain_stock_underlying_as_its_own_quote_symbol():
    """A real stock underlying (e.g. RELIANCE) needs no index-name mapping -- its F&O `name` and
    its real equity quote symbol are already identical, unlike the 3 real NSE indices above."""
    real_csv_header = (
        "instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,"
        "tick_size,lot_size,instrument_type,segment,exchange\n"
    )
    real_csv_rows = "1,1,RELIANCE26AUG2500CE,RELIANCE,0,2026-08-06,2500,0.05,250,CE,NFO-OPT,NFO\n"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/instruments/NFO":
            return httpx.Response(200, text=real_csv_header + real_csv_rows)
        if request.url.path == "/quote":
            requested_keys = request.url.params.get_list("i")
            if requested_keys[0].startswith("NSE:"):
                assert requested_keys == [
                    "NSE:RELIANCE"
                ], f"unmapped symbol changed: {requested_keys}"
                return httpx.Response(
                    200,
                    json={"status": "success", "data": {"NSE:RELIANCE": {"last_price": 2510.0}}},
                )
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": {"NFO:RELIANCE26AUG2500CE": {"last_price": 40.0, "oi": 200}},
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    adapter = _adapter_with_transport(handler)
    chain = await adapter.get_option_chain("RELIANCE", date(2026, 8, 6))

    assert chain.spot_price == 2510.0


@pytest.mark.asyncio
async def test_list_expiries_returns_real_distinct_future_expiries_sorted_ascending():
    real_csv_header = (
        "instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,"
        "tick_size,lot_size,instrument_type,segment,exchange\n"
    )
    real_csv_rows = (
        # 2 real distinct expiries for NIFTY (CE+PE each), 1 real expired date (excluded),
        # 1 real row for a different underlying (excluded)
        "1,1,NIFTY27FEB24000CE,NIFTY,0,2027-02-25,24000,0.05,50,CE,NFO-OPT,NFO\n"
        "2,2,NIFTY27FEB24000PE,NIFTY,0,2027-02-25,24000,0.05,50,PE,NFO-OPT,NFO\n"
        "3,3,NIFTY27JAN24000CE,NIFTY,0,2027-01-28,24000,0.05,50,CE,NFO-OPT,NFO\n"
        "4,4,NIFTY24JAN24000CE,NIFTY,0,2024-01-25,24000,0.05,50,CE,NFO-OPT,NFO\n"
        "5,5,BANKNIFTY27FEB50000CE,BANKNIFTY,0,2027-02-25,50000,0.05,25,CE,NFO-OPT,NFO\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/instruments/NFO"
        return httpx.Response(200, text=real_csv_header + real_csv_rows)

    adapter = _adapter_with_transport(handler)
    expiries = await adapter.list_expiries("NIFTY")

    assert expiries == [date(2027, 1, 28), date(2027, 2, 25)]
