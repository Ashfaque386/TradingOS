"""UpstoxAdapter integration tests against the REAL Upstox sandbox (Phase 4 Epic E4.1 exit
criterion: "Write integration tests against each broker's sandbox/test API environment").

Skipped entirely unless UPSTOX_ACCESS_TOKEN is configured with a genuine *sandbox* token
(generated via the "Generate" button inside a dedicated Sandbox App at
https://account.upstox.com/developer/apps#sandbox -- a production-flow OAuth token gets a 401
here, confirmed empirically). Safe to run: Upstox documents the sandbox as "closely emulat[ing]
the real API with no risk", and this was verified manually before being committed as a test --
placed/cancelled a real LIMIT order against the sandbox and confirmed no live exchange routing.

get_margin()/get_positions() are NOT exercised here: Upstox's sandbox currently 404s on the
portfolio/funds endpoints regardless of token validity (confirmed empirically, matching their
own docs noting partial sandbox coverage) -- those two methods stay covered by the mocked unit
tests in tests/unit/test_upstox_adapter.py only.
"""

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.brokers.base import OrderRequest
from src.brokers.upstox_adapter import UpstoxAdapter
from src.core.config import get_settings
from src.core.security import ROLE_PORTFOLIO_MANAGER
from tests.auth_helpers import auth_header, cleanup_user, create_authenticated_user
from tests.integration.test_orders_api import _cleanup_orders, _cleanup_strategy, _seed_strategy

settings = get_settings()
client = TestClient(app)

pytestmark = pytest.mark.skipif(
    not settings.upstox_access_token,
    reason="UPSTOX_ACCESS_TOKEN not configured -- see .env.example for the sandbox token flow",
)


@pytest.mark.asyncio
async def test_search_instrument_key_against_real_sandbox():
    async with UpstoxAdapter(
        access_token=settings.upstox_access_token, use_sandbox=settings.upstox_use_sandbox
    ) as adapter:
        instrument_key = await adapter.search_instrument_key("RELIANCE")

    assert instrument_key.startswith("NSE_EQ|")


@pytest.mark.asyncio
async def test_place_and_cancel_order_lifecycle_against_real_sandbox():
    async with UpstoxAdapter(
        access_token=settings.upstox_access_token, use_sandbox=settings.upstox_use_sandbox
    ) as adapter:
        instrument_key = await adapter.search_instrument_key("RELIANCE")

        # LIMIT price far below any plausible market price so the order stays open rather than
        # filling immediately -- keeps the cancel step deterministic.
        order = OrderRequest(
            symbol=instrument_key,
            side="BUY",
            order_type="LIMIT",
            quantity=1,
            product="INTRADAY",
            limit_price=100.0,
        )
        placed = await adapter.place_order(order)
        assert placed.broker_order_id

        book = await adapter.get_order_book()
        assert any(o.broker_order_id == placed.broker_order_id for o in book)

        cancelled = await adapter.cancel_order(placed.broker_order_id)
        assert cancelled.broker_order_id == placed.broker_order_id
        assert cancelled.status in ("CANCELLED", "FILLED", "REJECTED")


@pytest.mark.asyncio
async def test_place_and_cancel_order_through_the_real_orders_endpoint():
    """REL-055: the same real place+cancel lifecycle above, but end-to-end through
    POST/DELETE /api/v1/orders (src/api/routers/orders.py) rather than calling UpstoxAdapter
    directly -- proves the new endpoint's real compliance-check -> broker.place_order() ->
    Order-row-persistence chain against a genuinely real broker, not a mock. Extends this file's
    own established real-sandbox convention rather than duplicating a second sandbox test file.
    """
    strategy_id = _seed_strategy()
    user_id, token = create_authenticated_user(ROLE_PORTFOLIO_MANAGER)
    order_id = None
    adapter = UpstoxAdapter(
        access_token=settings.upstox_access_token, use_sandbox=settings.upstox_use_sandbox
    )
    try:
        with patch("src.api.routers.orders.build_broker", return_value=adapter):
            response = client.post(
                "/api/v1/orders",
                json={
                    "strategy_id": str(strategy_id),
                    "symbol": "RELIANCE",
                    "side": "BUY",
                    "quantity": 1,
                    "order_type": "LIMIT",
                    "limit_price": 100.0,
                    "account_scope": "Live",
                    "confirm_live_order": True,
                },
                headers=auth_header(token),
            )
        assert response.status_code == 201
        body = response.json()
        assert body["broker_order_id"]
        order_id = uuid.UUID(body["order_id"])

        with patch("src.api.routers.orders.build_broker", return_value=adapter):
            cancel_response = client.delete(
                f"/api/v1/orders/{order_id}", headers=auth_header(token)
            )
        assert cancel_response.status_code == 200
        assert cancel_response.json()["status"] in ("CANCELLED", "FILLED", "REJECTED")
    finally:
        # Not adapter.aclose() here: TestClient runs each request in its own internal event
        # loop, which is already torn down by the time this outer async test function resumes
        # -- closing the adapter's real httpx client here would race that loop's own teardown
        # (a test-harness artifact, not a real production concern; a real request lives inside
        # FastAPI's own single, correctly-managed loop for its whole lifetime). The client is a
        # short-lived test-local object, safe to leave for GC.
        if order_id is not None:
            _cleanup_orders(order_id)
        cleanup_user(user_id)
        _cleanup_strategy(strategy_id)
