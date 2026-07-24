"""WebSocket Latency Guard (Phase 4 Epic E4.2), per Phase_9_Master_Implementation_Guide.md §5
Risk Register:

  "Latency Spikes (WebSockets lagging behind live market): Prometheus alerts if WebSocket
  latency > 100ms. If triggered, the system pauses live trading until synced."

Unlike `MaxDrawdownKillSwitch` (src/engine/risk/kill_switch.py), which latches until a human
explicitly resets it, this pause clears itself automatically the next time latency is measured
back under the threshold -- "pauses ... until synced" describes a transient, self-recovering
condition (the data feed catching up), not an emergency requiring human review.
"""

from dataclasses import dataclass

DEFAULT_WS_LATENCY_THRESHOLD_SECONDS = 0.1


@dataclass(frozen=True)
class LatencyCheckResult:
    latency_seconds: float
    threshold_seconds: float
    paused: bool


class WebSocketLatencyGuard:
    def __init__(self, threshold_seconds: float = DEFAULT_WS_LATENCY_THRESHOLD_SECONDS) -> None:
        self.threshold_seconds = threshold_seconds
        self._paused = False
        self._last_latency_seconds: float | None = None

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def last_latency_seconds(self) -> float | None:
        return self._last_latency_seconds

    def record(self, latency_seconds: float) -> LatencyCheckResult:
        self._last_latency_seconds = latency_seconds
        self._paused = latency_seconds > self.threshold_seconds
        return LatencyCheckResult(
            latency_seconds=latency_seconds,
            threshold_seconds=self.threshold_seconds,
            paused=self._paused,
        )
