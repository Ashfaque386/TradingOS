"""Max Drawdown Kill Switch (Phase 3 Epic E3.4, Rule 1), per Phase_6_Trading_Engine_Design.md
§4 -- part of the **hardcoded** Risk & Portfolio Engine ("the AI cannot modify these rules"):

  "Max Drawdown Kill Switch: If the global portfolio drawdown exceeds 15% (or a configurable
  threshold), the engine halts all AI strategy deployments and liquidates all open positions
  automatically."

This module owns *detection* only: tracking the portfolio's running peak equity and flagging a
breach. The actual side effects it triggers (auto-liquidation, pausing AI deployment loops) are
the live-execution layer's responsibility (Phase 4) and are wired to this result, not implemented
here -- this stays a pure, easily-unit-tested state machine.
"""

from dataclasses import dataclass

DEFAULT_KILL_SWITCH_THRESHOLD = 0.15


@dataclass(frozen=True)
class KillSwitchResult:
    drawdown: float
    threshold: float
    triggered: bool


class MaxDrawdownKillSwitch:
    """Stateful, latching kill switch: tracks the running peak equity across successive
    `update()` calls and flags a breach once drawdown from that peak reaches `threshold`. Once
    triggered it stays triggered -- even if equity later recovers above the breach level --
    until `reset()` is called explicitly. A hardcoded risk gate that silently un-alarms itself
    the moment the market ticks back up would defeat the point of "halts all AI deployment
    loops"; clearing it is a deliberate, auditable human action."""

    def __init__(self, threshold: float = DEFAULT_KILL_SWITCH_THRESHOLD):
        self.threshold = threshold
        self._peak_equity: float | None = None
        self._triggered = False

    @property
    def triggered(self) -> bool:
        return self._triggered

    def update(self, equity: float) -> KillSwitchResult:
        if self._peak_equity is None or equity > self._peak_equity:
            self._peak_equity = equity

        drawdown = (self._peak_equity - equity) / self._peak_equity if self._peak_equity else 0.0
        if drawdown >= self.threshold:
            self._triggered = True

        return KillSwitchResult(
            drawdown=drawdown, threshold=self.threshold, triggered=self._triggered
        )

    def trip(self) -> None:
        """Manual emergency stop (API-084): forces the switch into the triggered state
        regardless of measured drawdown. Used for a human- or Risk-Manager-Agent-initiated
        halt that doesn't wait for the numeric threshold to be crossed naturally."""
        self._triggered = True

    def reset(self) -> None:
        """Explicit human acknowledgement that a triggered kill switch has been reviewed and
        AI deployment loops may resume. Also resets the tracked peak so drawdown is measured
        fresh from the equity at reset time, not the pre-breach high."""
        self._triggered = False
        self._peak_equity = None
