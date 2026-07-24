"""WebSocketLatencyGuard tests (Phase 4 Epic E4.2), per Phase_9_Master_Implementation_Guide.md
§5 Risk Register: pauses on a latency breach, auto-recovers once latency is back under
threshold (unlike MaxDrawdownKillSwitch, which requires an explicit human reset).
"""

from src.engine.risk.ws_latency_guard import WebSocketLatencyGuard


def test_starts_unpaused():
    guard = WebSocketLatencyGuard(threshold_seconds=0.1)
    assert guard.paused is False
    assert guard.last_latency_seconds is None


def test_a_latency_reading_under_threshold_stays_unpaused():
    guard = WebSocketLatencyGuard(threshold_seconds=0.1)
    result = guard.record(0.05)

    assert result.paused is False
    assert guard.paused is False
    assert guard.last_latency_seconds == 0.05


def test_a_latency_reading_over_threshold_pauses():
    guard = WebSocketLatencyGuard(threshold_seconds=0.1)
    result = guard.record(0.25)

    assert result.paused is True
    assert guard.paused is True
    assert result.latency_seconds == 0.25
    assert result.threshold_seconds == 0.1


def test_pause_clears_automatically_once_latency_recovers():
    guard = WebSocketLatencyGuard(threshold_seconds=0.1)
    guard.record(0.3)
    assert guard.paused is True

    guard.record(0.02)  # no explicit reset() call, unlike MaxDrawdownKillSwitch

    assert guard.paused is False


def test_a_reading_exactly_at_threshold_does_not_pause():
    guard = WebSocketLatencyGuard(threshold_seconds=0.1)
    result = guard.record(0.1)

    assert result.paused is False
