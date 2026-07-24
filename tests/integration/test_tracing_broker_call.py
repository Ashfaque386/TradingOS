"""Real httpx-instrumented trace continuity test (Phase 4 Epic E4.2), per
Phase_8_DevOps_Architecture.md §5: "A single trace ID follows a request from... FastAPI ->
Redis Queue -> Execution Engine -> Broker API."

Uses the real `UpstoxAdapter` against the real sandbox (same safety posture as
tests/integration/test_upstox_sandbox.py) rather than a mocked HTTP transport: OpenTelemetry's
httpx instrumentation patches httpx's real network transport, not test doubles like
`httpx.MockTransport` -- confirmed empirically while building this test (a MockTransport-backed
call produced zero spans). A genuine network call is the only way to actually verify the
"Execution Engine -> Broker API" trace leg works.
"""

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from src.brokers.upstox_adapter import UpstoxAdapter
from src.core.config import get_settings
from src.observability.tracing import configure_tracing, get_tracer

settings = get_settings()

pytestmark = pytest.mark.skipif(
    not settings.upstox_access_token,
    reason="UPSTOX_ACCESS_TOKEN not configured -- see .env.example for the sandbox token flow",
)


@pytest.mark.asyncio
async def test_a_real_broker_call_shares_the_trace_id_of_its_calling_span():
    configure_tracing()
    provider = trace.get_tracer_provider()
    assert isinstance(provider, TracerProvider)

    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    tracer = get_tracer(__name__)
    async with UpstoxAdapter(
        access_token=settings.upstox_access_token, use_sandbox=settings.upstox_use_sandbox
    ) as adapter:
        with tracer.start_as_current_span("test.execution_engine_call"):
            await adapter.search_instrument_key("RELIANCE")

    spans = exporter.get_finished_spans()
    trace_ids = {span.context.trace_id for span in spans}
    assert len(trace_ids) == 1, (
        f"expected every span to share one trace ID, got {len(trace_ids)} distinct trace(s): "
        f"{[(s.name, s.context.trace_id) for s in spans]}"
    )

    names = {span.name for span in spans}
    assert "test.execution_engine_call" in names
    # At least one more span: the httpx-instrumented "Broker API" leg, auto-created as a child
    # of the manual span above -- this is the actual thing being verified.
    assert len(spans) >= 2, f"expected a child httpx span too, got only: {names}"
