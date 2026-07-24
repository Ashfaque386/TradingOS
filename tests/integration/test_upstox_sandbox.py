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

import pytest

from src.brokers.base import OrderRequest
from src.brokers.upstox_adapter import UpstoxAdapter
from src.core.config import get_settings

settings = get_settings()

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
