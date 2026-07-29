"""Dual-control risk-limit changes (REL-007 E7.4, SEC-013/041): the one explicit dual-control
line in Phase_12_Security_Design.md's RBAC matrix -- "Change hard risk parameters (max drawdown,
sector exposure) ... Yes (dual-control, SEC-013)". A change is staged by one privileged user and
must be confirmed by a second, distinct one before a real RiskLimit row is created.

Deliberately does NOT cover kill-switch trip/reset (src/api/routers/system.py) -- those are a
real-time emergency stop, and the design doc's own SEC-033 calls for kill-switch access to be
"independent of the public API path," the opposite direction from adding approval friction; the
RBAC matrix also lists "Trigger kill-switch" and "Change hard risk parameters (dual-control)" as
two separate rows with different treatment. Also does NOT cover "Vault/infra configuration"
(also named in SEC-013's text) -- no such mutation endpoint exists anywhere in this codebase
today, so there is nothing real to gate; inventing one here would be scope not actually built.

Approver role gate: SystemAdministrator + RiskManager only, per RiskLimit's own docstring
("always set by a human Risk Manager") -- PortfolioManager is deliberately excluded (confirmed
as the intended scope, not assumed).
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import require_role
from src.core.audit import write_audit_entry
from src.core.db import get_session
from src.core.security import ROLE_READ_ONLY_AUDITOR, ROLE_RISK_MANAGER, ROLE_SYSTEM_ADMINISTRATOR
from src.models.risk_limit_change_request import RiskLimitChangeRequest
from src.models.trading import RiskLimit
from src.models.user import User

router = APIRouter(prefix="/api/v1/risk-limits", tags=["risk-limits"])

_can_stage_or_confirm = require_role(ROLE_SYSTEM_ADMINISTRATOR, ROLE_RISK_MANAGER)
_can_read = require_role(ROLE_SYSTEM_ADMINISTRATOR, ROLE_RISK_MANAGER, ROLE_READ_ONLY_AUDITOR)


def _latest_risk_limit(session: Session, scope_type: str = "Global") -> RiskLimit | None:
    """Same query shape as src/api/routers/portfolio.py's own helper of the same name -- kept
    separate (not imported) since that one is hardcoded to scope_type="Global" as a private
    module-level function, not a shared utility."""
    return session.scalars(
        select(RiskLimit)
        .where(RiskLimit.scope_type == scope_type)
        .order_by(RiskLimit.effective_from.desc())
    ).first()


class ChangeRequestPayload(BaseModel):
    scope_type: str
    scope_id: uuid.UUID | None = None
    max_daily_loss: float
    max_position_size_pct: float | None = None
    max_sector_exposure_pct: float | None = None
    max_drawdown_pct: float | None = None
    effective_from: datetime


class ChangeRequestResponse(BaseModel):
    id: uuid.UUID
    status: str
    scope_type: str
    max_daily_loss: float
    staged_by_user_id: uuid.UUID
    confirmed_by_user_id: uuid.UUID | None
    resulting_risk_limit_id: uuid.UUID | None


def _to_response(row: RiskLimitChangeRequest) -> ChangeRequestResponse:
    return ChangeRequestResponse(
        id=row.id,
        status=row.status,
        scope_type=row.scope_type,
        max_daily_loss=float(row.max_daily_loss),
        staged_by_user_id=row.staged_by_user_id,
        confirmed_by_user_id=row.confirmed_by_user_id,
        resulting_risk_limit_id=row.resulting_risk_limit_id,
    )


class CurrentRiskLimitResponse(BaseModel):
    scope_type: str
    max_daily_loss: float
    max_position_size_pct: float | None
    max_sector_exposure_pct: float | None
    max_drawdown_pct: float | None
    effective_from: datetime


@router.get("/current", response_model=CurrentRiskLimitResponse | None)
def current(_user: User = Depends(_can_read)) -> CurrentRiskLimitResponse | None:
    with get_session() as session:
        limit = _latest_risk_limit(session)
        if limit is None:
            return None
        return CurrentRiskLimitResponse(
            scope_type=limit.scope_type,
            max_daily_loss=float(limit.max_daily_loss),
            max_position_size_pct=(
                float(limit.max_position_size_pct)
                if limit.max_position_size_pct is not None
                else None
            ),
            max_sector_exposure_pct=(
                float(limit.max_sector_exposure_pct)
                if limit.max_sector_exposure_pct is not None
                else None
            ),
            max_drawdown_pct=(
                float(limit.max_drawdown_pct) if limit.max_drawdown_pct is not None else None
            ),
            effective_from=limit.effective_from,
        )


@router.post("/change-requests", response_model=ChangeRequestResponse)
def stage_change(
    body: ChangeRequestPayload, user: User = Depends(_can_stage_or_confirm)
) -> ChangeRequestResponse:
    with get_session() as session:
        row = RiskLimitChangeRequest(
            scope_type=body.scope_type,
            scope_id=body.scope_id,
            max_daily_loss=body.max_daily_loss,
            max_position_size_pct=body.max_position_size_pct,
            max_sector_exposure_pct=body.max_sector_exposure_pct,
            max_drawdown_pct=body.max_drawdown_pct,
            effective_from=body.effective_from,
            status="PENDING",
            staged_by_user_id=user.id,
        )
        session.add(row)
        session.flush()
        write_audit_entry(
            session,
            actor_type="Human",
            actor_id=user.email,
            action="RISK_LIMIT_CHANGE_STAGED",
            entity_type="RiskLimitChangeRequest",
            entity_id=row.id,
            after_state={
                "scope_type": row.scope_type,
                "max_daily_loss": str(row.max_daily_loss),
                "max_position_size_pct": str(row.max_position_size_pct),
                "max_sector_exposure_pct": str(row.max_sector_exposure_pct),
                "max_drawdown_pct": str(row.max_drawdown_pct),
            },
        )
        session.commit()
        return _to_response(row)


@router.get("/change-requests", response_model=list[ChangeRequestResponse])
def list_change_requests(
    status: str | None = None, _user: User = Depends(_can_read)
) -> list[ChangeRequestResponse]:
    with get_session() as session:
        stmt = select(RiskLimitChangeRequest).order_by(RiskLimitChangeRequest.created_at.desc())
        if status is not None:
            stmt = stmt.where(RiskLimitChangeRequest.status == status)
        rows = session.scalars(stmt)
        return [_to_response(r) for r in rows]


@router.post("/change-requests/{request_id}/confirm", response_model=ChangeRequestResponse)
def confirm_change(
    request_id: uuid.UUID, user: User = Depends(_can_stage_or_confirm)
) -> ChangeRequestResponse:
    with get_session() as session:
        row = session.get(RiskLimitChangeRequest, request_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Change request not found")
        if row.status != "PENDING":
            raise HTTPException(status_code=400, detail=f"Change request is already {row.status}")
        if row.staged_by_user_id == user.id:
            # SEC-013's entire point: the confirmer must be a second, distinct privileged user.
            raise HTTPException(
                status_code=403,
                detail="Cannot confirm your own staged change (dual-control, SEC-013)",
            )

        before_limit = _latest_risk_limit(session, row.scope_type)
        new_limit = RiskLimit(
            scope_type=row.scope_type,
            scope_id=row.scope_id,
            max_daily_loss=row.max_daily_loss,
            max_position_size_pct=row.max_position_size_pct,
            max_sector_exposure_pct=row.max_sector_exposure_pct,
            max_drawdown_pct=row.max_drawdown_pct,
            set_by_user_id=user.id,
            effective_from=row.effective_from,
        )
        session.add(new_limit)
        session.flush()

        row.status = "APPROVED"
        row.confirmed_by_user_id = user.id
        row.decided_at = datetime.now(UTC)
        row.resulting_risk_limit_id = new_limit.id

        write_audit_entry(
            session,
            actor_type="Human",
            actor_id=user.email,
            action="RISK_LIMIT_CHANGE_APPROVED",
            entity_type="RiskLimitChangeRequest",
            entity_id=row.id,
            before_state={
                "max_daily_loss": str(before_limit.max_daily_loss) if before_limit else None
            },
            after_state={
                "max_daily_loss": str(new_limit.max_daily_loss),
                "resulting_risk_limit_id": str(new_limit.id),
                "staged_by_user_id": str(row.staged_by_user_id),
                "confirmed_by_user_id": str(user.id),
            },
        )
        session.commit()
        return _to_response(row)


class RejectPayload(BaseModel):
    reason: str


@router.post("/change-requests/{request_id}/reject", response_model=ChangeRequestResponse)
def reject_change(
    request_id: uuid.UUID, body: RejectPayload, user: User = Depends(_can_stage_or_confirm)
) -> ChangeRequestResponse:
    """Unlike confirm, a self-reject is allowed -- canceling your own proposal carries no
    dual-control risk (nothing takes effect either way)."""
    with get_session() as session:
        row = session.get(RiskLimitChangeRequest, request_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Change request not found")
        if row.status != "PENDING":
            raise HTTPException(status_code=400, detail=f"Change request is already {row.status}")

        row.status = "REJECTED"
        row.confirmed_by_user_id = user.id
        row.decided_at = datetime.now(UTC)
        row.rejection_reason = body.reason

        write_audit_entry(
            session,
            actor_type="Human",
            actor_id=user.email,
            action="RISK_LIMIT_CHANGE_REJECTED",
            entity_type="RiskLimitChangeRequest",
            entity_id=row.id,
            after_state={"reason": body.reason},
        )
        session.commit()
        return _to_response(row)
