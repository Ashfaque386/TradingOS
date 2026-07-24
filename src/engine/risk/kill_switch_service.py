"""Kill Switch service (Phase 3 Epic E3.4): wires the pure `MaxDrawdownKillSwitch` state
machine (src/engine/risk/kill_switch.py) to the concrete "auto-liquidate all open positions"
action named in Phase_6_Trading_Engine_Design.md §4 / API-084
(Phase_10_API_Design.md §14).

Liquidation here means the actions available given today's persistence layer: cancel every
still-open (PENDING) order and flatten every non-zero PortfolioPosition to zero. Actually
routing a real closing order through a broker is Phase 4 work (broker adapters don't exist
yet) -- this is correct, real behavior for everything that DOES exist today, not a stub.

"Pausing AI deployment loops" is exposed as the `is_tripped()` state itself: there is no
scheduler/deployment loop yet (a Phase 2 gap noted in Phase_14_Master_Development_Roadmap.md),
so a future scheduler is expected to check `is_tripped()` before triggering a run.

Module-level singleton state (`_kill_switch`, `_tripped_at`, `_trip_reason`) matches this being
a single-process FastAPI service in Phase 3/4 -- there is exactly one kill switch for the whole
system, not one per request.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.engine.risk.kill_switch import DEFAULT_KILL_SWITCH_THRESHOLD, MaxDrawdownKillSwitch
from src.models.trading import Order, PortfolioPosition

_kill_switch = MaxDrawdownKillSwitch(threshold=DEFAULT_KILL_SWITCH_THRESHOLD)
_tripped_at: datetime | None = None
_trip_reason: str | None = None


@dataclass(frozen=True)
class KillSwitchTripResult:
    status: str
    liquidated_positions: int
    cancelled_orders: int


def is_tripped() -> bool:
    return _kill_switch.triggered


def get_status() -> dict[str, str | None]:
    return {
        "state": "TRIPPED" if _kill_switch.triggered else "ARMED",
        "tripped_at": _tripped_at.isoformat() if _tripped_at else None,
    }


def trip(session: Session, *, reason: str) -> KillSwitchTripResult:
    """EMERGENCY STOP (API-084): cancels every open order and flattens every open position.
    Deliberately independent of Redis or any other non-Postgres infrastructure -- a safety-
    critical stop must not be able to fail because a cache or pub/sub broker is down."""
    global _tripped_at, _trip_reason
    _kill_switch.trip()
    _tripped_at = datetime.now(UTC)
    _trip_reason = reason

    open_orders = list(session.scalars(select(Order).where(Order.status == "PENDING")))
    for order in open_orders:
        order.status = "CANCELLED"
        order.rejection_reason = f"Kill switch: {reason}"

    open_positions = list(
        session.scalars(select(PortfolioPosition).where(PortfolioPosition.net_quantity != 0))
    )
    for position in open_positions:
        position.net_quantity = 0

    session.commit()

    return KillSwitchTripResult(
        status="TRIPPED",
        liquidated_positions=len(open_positions),
        cancelled_orders=len(open_orders),
    )


def reset() -> None:
    """SA-only re-arm after manual review (API-086)."""
    global _tripped_at, _trip_reason
    _kill_switch.reset()
    _tripped_at = None
    _trip_reason = None
