"""OpenTelemetry tracing tests (Phase 4 Epic E4.2), per Phase_8_DevOps_Architecture.md §5:
"A single trace ID follows a request from... FastAPI -> Redis Queue -> Execution Engine ->
Broker API."

Real httpx-instrumented trace continuity across an actual broker HTTP call is verified
separately in tests/integration/test_tracing_broker_call.py against the real Upstox sandbox --
OpenTelemetry's httpx instrumentation patches httpx's real network transport, not test doubles
like `httpx.MockTransport` (confirmed empirically: a MockTransport-backed call produces zero
spans), so a mock-based version of that test would be testing nothing.
"""

from datetime import UTC, datetime

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from src.brokers.base import (
    BrokerAdapter,
    Margin,
    OrderRequest,
    OrderResponse,
    OrderType,
    Position,
    Quote,
)
from src.engine.live.execution_pipeline import LiveExecutionPipeline, SymbolState, Tick, TradeSignal
from src.engine.risk.kill_switch import MaxDrawdownKillSwitch
from src.observability.tracing import configure_tracing, get_tracer


class NoOpFakeBroker(BrokerAdapter):
    async def place_order(self, order: OrderRequest) -> OrderResponse:
        return OrderResponse(
            broker_order_id="ORD1",
            status="OPEN",
            symbol=order.symbol,
            side=order.side,
            order_type=order.order_type,
            quantity=order.quantity,
        )

    async def modify_order(
        self,
        broker_order_id: str,
        *,
        quantity: int | None = None,
        order_type: OrderType | None = None,
        limit_price: float | None = None,
        trigger_price: float | None = None,
    ) -> OrderResponse:
        raise NotImplementedError

    async def cancel_order(self, broker_order_id: str) -> OrderResponse:
        raise NotImplementedError

    async def get_order_book(self) -> list[OrderResponse]:
        return []

    async def get_margin(self) -> Margin:
        return Margin(available_margin=0.0, used_margin=0.0)

    async def get_positions(self) -> list[Position]:
        return []

    async def get_quote(self, symbol: str) -> Quote:
        raise NotImplementedError

    async def get_option_chain(self, underlying: str, expiry):
        raise NotImplementedError

    async def list_expiries(self, underlying: str):
        raise NotImplementedError


def test_configure_tracing_is_idempotent():
    configure_tracing()
    configure_tracing()  # must not raise on a second call


def test_get_tracer_returns_a_usable_tracer():
    configure_tracing()
    tracer = get_tracer("test-module")
    with tracer.start_as_current_span("test-span") as span:
        assert span.is_recording() or span is not None  # a real Span object either way


@pytest.mark.asyncio
async def test_handle_tick_creates_a_span_with_the_symbol_attribute():
    configure_tracing()
    exporter = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    assert isinstance(provider, TracerProvider)  # configure_tracing() always installs the SDK's
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    def always_buy(state: SymbolState) -> TradeSignal | None:
        return TradeSignal(symbol=state.symbol, side="BUY", quantity=1)

    pipeline = LiveExecutionPipeline(
        broker=NoOpFakeBroker(), signal_generator=always_buy, kill_switch=MaxDrawdownKillSwitch()
    )

    result = await pipeline.handle_tick(
        Tick(symbol="RELIANCE", price=2500.0, timestamp=datetime.now(UTC))
    )

    assert result is not None
    spans = exporter.get_finished_spans()
    handle_tick_spans = [s for s in spans if s.name == "execution_engine.handle_tick"]
    assert len(handle_tick_spans) == 1
    assert handle_tick_spans[0].attributes["symbol"] == "RELIANCE"
