"""REL-036: src/api/routers/portfolio.py's real-broker-call error handling against the real
FastAPI app -- a broker-side failure other than NoBrokerConfigured (e.g. an expired daily
Zerodha token) must surface as a real 502, not an unhandled 500, so the frontend can distinguish
"configured but the call failed" from both "not configured" (503) and "configured, genuinely
empty" (200). Mirrors the try/except shape src/api/routers/broker_config.py::broker_order_book
already uses and this file's own new _get_positions/_get_margin helpers.
"""

from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)


def _real_shaped_http_status_error() -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://api.kite.trade/user/margins/equity")
    response = httpx.Response(403, request=request, text="Invalid or expired token")
    return httpx.HTTPStatusError("403 Forbidden", request=request, response=response)


@patch("src.api.routers.portfolio.build_broker")
def test_positions_returns_502_not_an_unhandled_500_on_a_real_broker_call_failure(
    mock_build_broker,
):
    fake_broker = AsyncMock()
    fake_broker.get_positions.side_effect = _real_shaped_http_status_error()
    mock_build_broker.return_value = fake_broker

    response = client.get("/api/v1/positions")
    assert response.status_code == 502


@patch("src.api.routers.portfolio.build_broker")
def test_margin_returns_502_not_an_unhandled_500_on_a_real_broker_call_failure(mock_build_broker):
    fake_broker = AsyncMock()
    fake_broker.get_margin.side_effect = _real_shaped_http_status_error()
    mock_build_broker.return_value = fake_broker

    response = client.get("/api/v1/portfolio/margin")
    assert response.status_code == 502


@patch("src.api.routers.portfolio.build_broker")
def test_pnl_returns_502_not_an_unhandled_500_when_positions_call_fails(mock_build_broker):
    fake_broker = AsyncMock()
    fake_broker.get_positions.side_effect = _real_shaped_http_status_error()
    mock_build_broker.return_value = fake_broker

    response = client.get("/api/v1/portfolio/pnl")
    assert response.status_code == 502
