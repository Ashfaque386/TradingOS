"""System control endpoints (Phase 3 Epic E3.4): the Kill-Switch & Emergency Controls group,
API-084/085/086 in Phase_10_API_Design.md §14.

Trip/reset require SystemAdministrator, PortfolioManager, or RiskManager per
Phase_12_Security_Design.md §2.2's "Trigger kill-switch / emergency liquidation" permission row
(src/api/deps.py's require_role). Status stays open (no auth dependency) like every other
read-only endpoint in this codebase -- this MVP auth pass only gates the sensitive mutations
(Phase_14_Master_Development_Roadmap.md §5.3), not a blanket relogin requirement for every GET.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.deps import require_role
from src.core.db import get_session
from src.core.security import ROLE_PORTFOLIO_MANAGER, ROLE_RISK_MANAGER, ROLE_SYSTEM_ADMINISTRATOR
from src.engine.risk import kill_switch_service
from src.models.user import User

router = APIRouter(prefix="/api/v1/system", tags=["system"])

_can_trigger_kill_switch = require_role(
    ROLE_SYSTEM_ADMINISTRATOR, ROLE_PORTFOLIO_MANAGER, ROLE_RISK_MANAGER
)


class KillSwitchTripRequest(BaseModel):
    reason: str


class KillSwitchTripResponse(BaseModel):
    status: str
    liquidated_positions: int


class KillSwitchStatusResponse(BaseModel):
    state: str
    tripped_at: str | None


class KillSwitchResetRequest(BaseModel):
    confirmation: bool


class KillSwitchResetResponse(BaseModel):
    status: str


@router.post("/kill-switch", response_model=KillSwitchTripResponse)
def trip_kill_switch(
    body: KillSwitchTripRequest, _user: User = Depends(_can_trigger_kill_switch)
) -> KillSwitchTripResponse:
    """API-084: EMERGENCY STOP -- cancels all open orders, liquidates all positions."""
    with get_session() as session:
        result = kill_switch_service.trip(session, reason=body.reason)
    return KillSwitchTripResponse(
        status=result.status, liquidated_positions=result.liquidated_positions
    )


@router.get("/kill-switch/status", response_model=KillSwitchStatusResponse)
def kill_switch_status() -> KillSwitchStatusResponse:
    """API-085: current kill-switch armed/tripped state."""
    return KillSwitchStatusResponse(**kill_switch_service.get_status())


@router.post("/kill-switch/reset", response_model=KillSwitchResetResponse)
def reset_kill_switch(
    body: KillSwitchResetRequest, _user: User = Depends(_can_trigger_kill_switch)
) -> KillSwitchResetResponse:
    """API-086: re-arm the system after manual review post-trip."""
    if not body.confirmation:
        raise HTTPException(status_code=400, detail="Reset requires confirmation=true")
    kill_switch_service.reset()
    return KillSwitchResetResponse(status="ARMED")
