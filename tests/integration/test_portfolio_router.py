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

from src.agents.control import KNOWN_AGENTS
from src.api.main import app
from src.brokers.base import Position

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


# REL-038: build_broker() resolves ONE adapter (Zerodha-primary/Upstox-fallback) -- a real,
# separately-funded Upstox account never shows up there as long as the Zerodha call itself
# succeeds, even with a genuinely empty account. The by-broker endpoints below query each real
# broker independently, so both real accounts are shown, never silently shadowed by one another.


@patch("src.api.routers.portfolio.build_upstox_adapter")
@patch("src.api.routers.portfolio.build_zerodha_adapter")
def test_margin_by_broker_reports_both_real_brokers_independently(
    mock_build_zerodha, mock_build_upstox
):
    from src.brokers.base import Margin

    zerodha = AsyncMock()
    zerodha.get_margin.return_value = Margin(available_margin=0.0, used_margin=0.0, raw={})
    mock_build_zerodha.return_value = zerodha

    upstox = AsyncMock()
    upstox.get_margin.return_value = Margin(available_margin=25000.0, used_margin=5000.0, raw={})
    mock_build_upstox.return_value = upstox

    response = client.get("/api/v1/portfolio/margin/by-broker")
    assert response.status_code == 200
    entries = {e["broker"]: e for e in response.json()}
    assert entries["Zerodha"]["configured"] is True
    assert entries["Zerodha"]["margin"]["available_margin"] == 0.0
    assert entries["Upstox"]["configured"] is True
    assert entries["Upstox"]["margin"]["available_margin"] == 25000.0


@patch("src.api.routers.portfolio.build_upstox_adapter")
@patch("src.api.routers.portfolio.build_zerodha_adapter")
def test_margin_by_broker_reports_not_configured_without_failing_the_other_broker(
    mock_build_zerodha, mock_build_upstox
):
    from src.brokers.base import Margin
    from src.brokers.factory import NoBrokerConfigured

    mock_build_zerodha.side_effect = NoBrokerConfigured("Zerodha is not configured")
    upstox = AsyncMock()
    upstox.get_margin.return_value = Margin(available_margin=100.0, used_margin=0.0, raw={})
    mock_build_upstox.return_value = upstox

    response = client.get("/api/v1/portfolio/margin/by-broker")
    assert response.status_code == 200
    entries = {e["broker"]: e for e in response.json()}
    assert entries["Zerodha"]["configured"] is False
    assert entries["Zerodha"]["margin"] is None
    assert entries["Upstox"]["configured"] is True
    assert entries["Upstox"]["margin"]["available_margin"] == 100.0


@patch("src.api.routers.portfolio.build_upstox_adapter")
@patch("src.api.routers.portfolio.build_zerodha_adapter")
def test_margin_by_broker_reports_a_real_call_failure_without_500ing_the_whole_request(
    mock_build_zerodha, mock_build_upstox
):
    from src.brokers.base import Margin

    zerodha = AsyncMock()
    zerodha.get_margin.side_effect = _real_shaped_http_status_error()
    mock_build_zerodha.return_value = zerodha

    upstox = AsyncMock()
    upstox.get_margin.return_value = Margin(available_margin=10.0, used_margin=0.0, raw={})
    mock_build_upstox.return_value = upstox

    response = client.get("/api/v1/portfolio/margin/by-broker")
    assert response.status_code == 200
    entries = {e["broker"]: e for e in response.json()}
    assert entries["Zerodha"]["configured"] is True
    assert entries["Zerodha"]["margin"] is None
    assert entries["Zerodha"]["error"] is not None
    assert entries["Upstox"]["margin"]["available_margin"] == 10.0


@patch("src.api.routers.portfolio.build_upstox_adapter")
@patch("src.api.routers.portfolio.build_zerodha_adapter")
def test_positions_by_broker_reports_both_real_brokers_independently(
    mock_build_zerodha, mock_build_upstox
):
    from src.brokers.base import Position

    zerodha = AsyncMock()
    zerodha.get_positions.return_value = []
    mock_build_zerodha.return_value = zerodha

    upstox = AsyncMock()
    upstox.get_positions.return_value = [
        Position(symbol="RELIANCE", net_quantity=10, average_price=2500.0)
    ]
    mock_build_upstox.return_value = upstox

    response = client.get("/api/v1/positions/by-broker")
    assert response.status_code == 200
    entries = {e["broker"]: e for e in response.json()}
    assert entries["Zerodha"]["positions"] == []
    assert entries["Upstox"]["positions"][0]["symbol"] == "RELIANCE"


# --- Dashboard summary (API-006, REL-062) ---------------------------------------------------


@patch("src.api.routers.portfolio.build_broker")
def test_dashboard_summary_composes_real_pnl_and_agent_activity_counts(mock_build_broker):
    fake_broker = AsyncMock()
    fake_broker.get_positions.return_value = [
        Position(
            symbol="TCS",
            net_quantity=10,
            average_price=100.0,
            last_price=110.0,
            unrealized_pnl=100.0,
            realized_pnl=0.0,
        ),
        Position(
            symbol="INFY",
            net_quantity=0,
            average_price=0.0,
            last_price=0.0,
            unrealized_pnl=0.0,
            realized_pnl=50.0,
        ),
    ]
    mock_build_broker.return_value = fake_broker

    response = client.get("/api/v1/dashboard/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["unrealized_pnl"] == 100.0
    assert body["realized_pnl"] == 50.0
    assert body["total_pnl"] == 150.0
    # INFY has net_quantity=0 (a closed/flat position) -- not counted as "open".
    assert body["open_positions_count"] == 1
    assert body["total_agents"] == len(KNOWN_AGENTS)
    assert 0 <= body["active_agents"] <= body["total_agents"]


@patch("src.api.routers.portfolio.build_broker")
def test_dashboard_summary_returns_502_not_an_unhandled_500_on_a_real_broker_call_failure(
    mock_build_broker,
):
    fake_broker = AsyncMock()
    fake_broker.get_positions.side_effect = _real_shaped_http_status_error()
    mock_build_broker.return_value = fake_broker

    response = client.get("/api/v1/dashboard/summary")
    assert response.status_code == 502
