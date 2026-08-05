"""REL-009 E9.1: the real /metrics endpoint (src/api/routers/metrics.py) against the real
FastAPI app -- proves the new metrics genuinely appear in Prometheus text-exposition format
after the code paths that observe them run, not just that the endpoint exists."""

import asyncio
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from src.api.main import app
from src.brokers.base import BrokerAdapter, Margin, OrderRequest, OrderResponse, Position, Quote
from src.data.reference.nse_holiday_calendar import is_trading_holiday
from src.engine.live.execution_pipeline import LiveExecutionPipeline, Tick, TradeSignal
from src.engine.risk.kill_switch import MaxDrawdownKillSwitch

client = TestClient(app)


class _RecordingBroker(BrokerAdapter):
    async def place_order(self, order: OrderRequest) -> OrderResponse:
        return OrderResponse(
            broker_order_id="test-order-metrics",
            status="PENDING",
            symbol=order.symbol,
            side=order.side,
            order_type=order.order_type,
            quantity=order.quantity,
        )

    async def modify_order(self, broker_order_id, **kwargs) -> OrderResponse:
        raise AssertionError("not used in this test")

    async def cancel_order(self, broker_order_id: str) -> OrderResponse:
        raise AssertionError("not used in this test")

    async def get_order_book(self) -> list[OrderResponse]:
        return []

    async def get_margin(self) -> Margin:
        raise AssertionError("not used in this test")

    async def get_positions(self) -> list[Position]:
        return []

    async def get_quote(self, symbol: str) -> Quote:
        raise AssertionError("not used in this test")

    async def get_option_chain(self, underlying: str, expiry):
        raise AssertionError("not used in this test")


def test_metrics_endpoint_returns_prometheus_text_exposition_format() -> None:
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "# HELP tradingos_ws_stream_latency_seconds" in response.text
    assert "# HELP tradingos_agent_run_duration_seconds" in response.text
    assert "# HELP tradingos_order_execution_latency_seconds" in response.text


def _extract_count(metrics_text: str, metric_name: str) -> float:
    for line in metrics_text.splitlines():
        if line.startswith(metric_name):
            return float(line.split()[-1])
    raise AssertionError(f"{metric_name} not found in /metrics output")


def test_order_execution_latency_metric_increments_on_a_real_dispatched_signal() -> None:
    before = _extract_count(
        client.get("/metrics").text, "tradingos_order_execution_latency_seconds_count"
    )

    signal = TradeSignal(
        symbol="RELIANCE", side="BUY", quantity=1, order_type="LIMIT", limit_price=1.0
    )
    pipeline = LiveExecutionPipeline(
        broker=_RecordingBroker(),
        signal_generator=lambda state: signal,
        kill_switch=MaxDrawdownKillSwitch(),
    )
    asyncio.run(
        pipeline.handle_tick(Tick(symbol="RELIANCE", price=2500.0, timestamp=datetime.now(UTC)))
    )

    after = _extract_count(
        client.get("/metrics").text, "tradingos_order_execution_latency_seconds_count"
    )
    assert after == before + 1


def test_trading_holiday_gauge_matches_the_real_holiday_calendar_for_today() -> None:
    """REL-020 E20.1: proves the gauge the market-hours SLO recording rule gates on
    (monitoring/rules/availability.yml) is set from the real calendar for the real current IST
    date, not a stale/default value -- independently recomputes the expected value from
    src/data/reference/nse_holiday_calendar.py rather than asserting a hardcoded 0 or 1, so this
    test stays correct on both trading days and weekends/holidays without editing."""
    today_ist = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    expected = 1.0 if is_trading_holiday(today_ist) else 0.0

    value = _extract_count(client.get("/metrics").text, "tradingos_trading_holiday_today")

    assert value == expected
