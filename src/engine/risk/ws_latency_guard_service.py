"""Module-level singleton `WebSocketLatencyGuard` (Phase 4 Epic E4.2) -- same single-process
pattern as src/engine/risk/kill_switch_service.py: there is exactly one latency guard for the
whole system, not one per WebSocket connection, so a breach on any stream pauses live trading
system-wide.
"""

from src.engine.risk.ws_latency_guard import (
    DEFAULT_WS_LATENCY_THRESHOLD_SECONDS,
    WebSocketLatencyGuard,
)

_guard = WebSocketLatencyGuard(threshold_seconds=DEFAULT_WS_LATENCY_THRESHOLD_SECONDS)


def get_latency_guard() -> WebSocketLatencyGuard:
    return _guard
