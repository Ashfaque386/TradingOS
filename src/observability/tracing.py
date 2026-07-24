"""OpenTelemetry distributed tracing setup (Phase 4 Epic E4.2), per
Phase_8_DevOps_Architecture.md §5:

  "A single trace ID follows a request from the Next.js frontend -> FastAPI -> Redis Queue ->
  Execution Engine -> Broker API. If order execution latency spikes above 50ms, OpenTelemetry
  highlights exactly which microservice caused the bottleneck."

The frontend leg doesn't exist yet (no Next.js app, E4.3) -- FastAPI's instrumentation already
continues an incoming W3C `traceparent` header when present, so a future frontend using an OTel
JS SDK plugs into this trace chain without any backend change. The rest of the chain (FastAPI ->
Redis tick -> Execution Engine -> Broker API) is instrumented now: FastAPI auto-instrumentation,
httpx auto-instrumentation (covers every broker HTTP call, since `UpstoxAdapter` uses
`httpx.AsyncClient`), and manual spans in the tick-listener/execution-pipeline/execution-agent
for the parts that aren't an inbound HTTP request or an outbound httpx call.

No OTLP collector runs in this docker-compose stack yet -- exporting is optional, same pattern
as LangSmith tracing (src/agents/llm_router.py): with `OTEL_EXPORTER_OTLP_ENDPOINT` unset, the
SDK still creates and propagates real trace/span IDs across every instrumented call (that's
what actually satisfies "a single trace ID follows a request"), it just has nothing configured
to ship spans to. Point it at a real collector (Jaeger, Tempo, ...) once one is deployed.
"""

from typing import TYPE_CHECKING

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Tracer

from src.core.config import get_settings

if TYPE_CHECKING:
    from fastapi import FastAPI

_configured = False


def configure_tracing(app: "FastAPI | None" = None) -> None:
    """Idempotent: safe to call more than once (e.g. once at FastAPI startup, once per test
    module) -- only the first call actually installs the global TracerProvider/instrumentors."""
    global _configured
    if _configured:
        if app is not None:
            _instrument_app(app)
        return

    settings = get_settings()
    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: settings.otel_service_name}))
    if settings.otel_exporter_otlp_endpoint:
        exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    HTTPXClientInstrumentor().instrument()

    if app is not None:
        _instrument_app(app)

    _configured = True


def _instrument_app(app: "FastAPI") -> None:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app)


def get_tracer(name: str) -> Tracer:
    return trace.get_tracer(name)
