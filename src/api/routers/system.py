"""System control endpoints (Phase 3 Epic E3.4): the Kill-Switch & Emergency Controls group,
API-084/085/086 in Phase_10_API_Design.md §14.

Trip/reset require SystemAdministrator, PortfolioManager, or RiskManager per
Phase_12_Security_Design.md §2.2's "Trigger kill-switch / emergency liquidation" permission row
(src/api/deps.py's require_role). Status stays open (no auth dependency) like every other
read-only endpoint in this codebase -- this MVP auth pass only gates the sensitive mutations
(Phase_14_Master_Development_Roadmap.md §5.3), not a blanket relogin requirement for every GET.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.deps import get_current_user, require_role
from src.core import vault_transit
from src.core.api_rate_limit import peek
from src.core.config import get_settings
from src.core.db import get_session
from src.core.security import ROLE_PORTFOLIO_MANAGER, ROLE_RISK_MANAGER, ROLE_SYSTEM_ADMINISTRATOR
from src.core.vault_transit import VaultTransitUnavailableError
from src.engine.risk import kill_switch_service
from src.memory.redis_client import get_redis_client
from src.models.user import User

router = APIRouter(prefix="/api/v1/system", tags=["system"])

_can_trigger_kill_switch = require_role(
    ROLE_SYSTEM_ADMINISTRATOR, ROLE_PORTFOLIO_MANAGER, ROLE_RISK_MANAGER, audit_denials=True
)
_can_rotate_jwt_key = require_role(ROLE_SYSTEM_ADMINISTRATOR, audit_denials=True)


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
        result = kill_switch_service.trip(session, reason=body.reason, actor_id=_user.email)
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
    with get_session() as session:
        kill_switch_service.reset(session, actor_id=_user.email)
    return KillSwitchResetResponse(status="ARMED")


class JwtSigningKeyRotateResponse(BaseModel):
    new_version: int


@router.post("/jwt-signing-key/rotate", response_model=JwtSigningKeyRotateResponse)
def rotate_jwt_signing_key(
    _user: User = Depends(_can_rotate_jwt_key),
) -> JwtSigningKeyRotateResponse:
    """REL-007 E7.2 (SEC-011): rotates the Vault Transit JWT-signing key. Every access token
    signed with a version below the new one stops verifying immediately (see
    src/core/vault_transit.py's rotate_key() and src/core/security.py's decode_access_token()
    for the mechanism) -- this is a genuine, real-time "log everyone out" action, restricted to
    SystemAdministrator accordingly."""
    try:
        new_version = vault_transit.rotate_key()
    except VaultTransitUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return JwtSigningKeyRotateResponse(new_version=new_version)


class RateLimitStatusResponse(BaseModel):
    limit: int
    remaining: int
    window_seconds: int
    reset_at: datetime


@router.get("/rate-limit/status", response_model=RateLimitStatusResponse)
def rate_limit_status(user: User = Depends(get_current_user)) -> RateLimitStatusResponse:
    """API-014. Reads the caller's own current-window usage back out of
    RateLimitMiddleware's real counter (src/core/api_rate_limit.py::peek, read-only -- this call
    itself doesn't spend from the budget it reports) -- the same "user:{id}" key the middleware
    used for this exact request. "My own data," not a privileged action, so this stays gated to
    any authenticated caller rather than a specific role, matching this router's own precedent of
    leaving plain reads open where nothing sensitive is exposed."""
    settings = get_settings()
    result = peek(
        f"user:{user.id}",
        redis_client=get_redis_client(),
        limit=settings.api_rate_limit_requests,
        window_seconds=settings.api_rate_limit_window_seconds,
    )
    return RateLimitStatusResponse(
        limit=result.limit,
        remaining=result.remaining,
        window_seconds=settings.api_rate_limit_window_seconds,
        reset_at=result.reset_at,
    )
