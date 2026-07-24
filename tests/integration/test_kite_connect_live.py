"""KiteConnectAdapter integration tests against the REAL, LIVE Kite Connect API (Phase 4 Epic
E4.1 exit criterion: "Write integration tests against each broker's sandbox/test API
environment").

SAFETY: Kite Connect has no sandbox -- this is real production API access to a real trading
account. Only read-only endpoints (get_margin, get_positions, get_order_book) are exercised
here. place_order/modify_order/cancel_order are deliberately NEVER called against the live API
in any automated test (see tests/unit/test_kite_connect_adapter.py, which covers those three
methods exhaustively via mocked HTTP instead) -- placing a real order carries real financial
risk and is out of scope for what an automated test suite should ever do against this broker.

Skipped entirely unless ZERODHA_ACCESS_TOKEN is configured with a genuine, freshly-generated
token (Kite tokens expire daily around 6 AM IST with no refresh token -- see .env.example for
the login/token-exchange flow).
"""

import pytest

from src.brokers.kite_connect_adapter import KiteConnectAdapter
from src.core.config import get_settings

settings = get_settings()

pytestmark = pytest.mark.skipif(
    not settings.zerodha_access_token,
    reason="ZERODHA_ACCESS_TOKEN not configured -- see .env.example for the login/token flow",
)


@pytest.mark.asyncio
async def test_get_margin_against_the_real_account():
    async with KiteConnectAdapter(
        api_key=settings.zerodha_api_key, access_token=settings.zerodha_access_token
    ) as adapter:
        margin = await adapter.get_margin()

    assert margin.available_margin >= 0.0
    assert margin.used_margin >= 0.0


@pytest.mark.asyncio
async def test_get_positions_against_the_real_account():
    async with KiteConnectAdapter(
        api_key=settings.zerodha_api_key, access_token=settings.zerodha_access_token
    ) as adapter:
        positions = await adapter.get_positions()

    assert isinstance(positions, list)  # may legitimately be empty -- that's a valid real state


@pytest.mark.asyncio
async def test_get_order_book_against_the_real_account():
    async with KiteConnectAdapter(
        api_key=settings.zerodha_api_key, access_token=settings.zerodha_access_token
    ) as adapter:
        orders = await adapter.get_order_book()

    assert isinstance(orders, list)  # may legitimately be empty
