"""Prometheus metrics (Phase 4 Epic E4.2), per Phase_8_DevOps_Architecture.md §5 ("Metrics:
Prometheus & Grafana") and Phase_9_Master_Implementation_Guide.md §5 Risk Register:
"Prometheus alerts if WebSocket latency > 100ms."
"""

from prometheus_client import Histogram

WS_STREAM_LATENCY_SECONDS = Histogram(
    "tradingos_ws_stream_latency_seconds",
    "Latency (seconds) of relaying a message through a TradingOS WebSocket stream endpoint",
    labelnames=("stream",),
)
