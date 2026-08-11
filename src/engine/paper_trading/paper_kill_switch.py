"""Paper-account-scoped kill switch (REL-034).

Deliberately a SEPARATE `MaxDrawdownKillSwitch` instance from `src/engine/risk/kill_switch_
service.py`'s shared production singleton -- sharing it would be a real correctness bug in
either direction: a paper account's own drawdown (virtual money) must never halt real live
trading, and this system currently has no strategy in Live status at all (per the Go-Live
Readiness Gate), so treating paper losses as equivalent to a real trading halt would be actively
wrong, not just imprecise.

The dependency runs the other way, defensively: if the real production kill switch is ever
tripped (`kill_switch_service.is_tripped()`), paper execution should also pause -- something
serious enough to halt real trading is a reasonable signal to stop autonomously testing more
strategies too, pending human review. One-directional only; resetting the paper switch never
touches the production one.

Module-level singleton, matching `kill_switch_service.py`'s own stated reasoning: exactly one
paper account exists system-wide, not one per request.
"""

from src.engine.risk import kill_switch_service
from src.engine.risk.kill_switch import DEFAULT_KILL_SWITCH_THRESHOLD, MaxDrawdownKillSwitch

_paper_kill_switch = MaxDrawdownKillSwitch(threshold=DEFAULT_KILL_SWITCH_THRESHOLD)


def get_paper_kill_switch() -> MaxDrawdownKillSwitch:
    return _paper_kill_switch


def is_paper_trading_halted() -> bool:
    """True if either the paper account's own drawdown breached its threshold, or the real
    production kill switch is tripped (defensive global halt, one-directional)."""
    return _paper_kill_switch.triggered or kill_switch_service.is_tripped()


def update_and_check(equity: float) -> bool:
    """Feeds the latest computed equity into the paper switch's drawdown tracking and returns
    whether paper execution should proceed. Call before every paper trade attempt (both the
    daily signal job and the intraday pipeline)."""
    _paper_kill_switch.update(equity)
    return not is_paper_trading_halted()


def reset() -> None:
    """Explicit human acknowledgement -- resets only the paper-scoped switch, never the
    production one."""
    _paper_kill_switch.reset()
