"""Module-level singleton `WebSocketLatencyGuard` (Phase 4 Epic E4.2) -- same single-process
pattern as src/engine/risk/kill_switch_service.py: there is exactly one latency guard for the
whole system, not one per WebSocket connection, so a breach on any stream pauses live trading
system-wide.

REL-009 E9.1 fix: `settings.ws_latency_pause_threshold_seconds` (src/core/config.py) was a real
config field that nothing ever read -- the guard was hardcoded to
`ws_latency_guard.py`'s own `DEFAULT_WS_LATENCY_THRESHOLD_SECONDS` constant regardless of what was
configured in `.env`. Now genuinely wired: the guard's threshold is the real setting value
(falling back to the same default), so it's actually configurable, matching what the setting's
own docstring already claimed.
"""

from src.core.config import get_settings
from src.engine.risk.ws_latency_guard import WebSocketLatencyGuard

_guard = WebSocketLatencyGuard(threshold_seconds=get_settings().ws_latency_pause_threshold_seconds)


def get_latency_guard() -> WebSocketLatencyGuard:
    return _guard
