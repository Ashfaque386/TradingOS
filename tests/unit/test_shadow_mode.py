"""ShadowModeAdapter unit tests (Phase 4 Epic E4.4): the Zerodha path is tested here because it
needs no live token at all -- it's local-only by design (Kite Connect has no sandbox, see
src/brokers/shadow_mode.py's module docstring). The Upstox real-sandbox path is exercised in
tests/integration/test_shadow_mode_api.py, gated behind a live-broker skip like every other real
Upstox/Zerodha call in this codebase.
"""

import httpx
import pytest

from src.brokers.base import OrderRequest
from src.brokers.kite_connect_adapter import KiteConnectAdapter
from src.brokers.shadow_mode import ShadowModeAdapter, UnsupportedBrokerError


def _kite_adapter_that_fails_any_real_request() -> KiteConnectAdapter:
    """Proves the Zerodha Shadow Mode path never calls the network at all: any HTTP request
    reaching this transport fails the test outright, rather than merely asserting no order was
    placed after the fact."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(
            f"Shadow Mode must never make a real HTTP call for Zerodha (no sandbox exists), "
            f"but one was attempted: {request.method} {request.url}"
        )

    adapter = KiteConnectAdapter(api_key="test-key", access_token="test-token")
    adapter._client = httpx.AsyncClient(
        base_url=adapter._client.base_url,
        headers=adapter._client.headers,
        transport=httpx.MockTransport(handler),
    )
    return adapter


@pytest.mark.asyncio
async def test_zerodha_shadow_attempt_validates_locally_without_any_network_call():
    adapter = _kite_adapter_that_fails_any_real_request()
    shadow = ShadowModeAdapter(adapter, broker_name="zerodha")
    order = OrderRequest(symbol="INFY", side="BUY", order_type="MARKET", quantity=10)

    result = await shadow.attempt_order(order)

    assert result.outcome == "Validated"
    assert result.used_real_sandbox is False
    assert result.error_detail is None
    assert result.request_payload["tradingsymbol"] == "INFY"
    assert result.request_payload["product"] == "MIS"  # INTRADAY -> Kite's real product code
    assert result.latency_ms >= 0


@pytest.mark.asyncio
async def test_unsupported_broker_type_raises_rather_than_guessing():
    class FakeBroker:
        pass

    shadow = ShadowModeAdapter(FakeBroker(), broker_name="fake")  # type: ignore[arg-type]
    order = OrderRequest(symbol="INFY", side="BUY", order_type="MARKET", quantity=10)

    with pytest.raises(UnsupportedBrokerError):
        await shadow.attempt_order(order)
