"""Approval-gate API (spec T047, contracts/rest-api.md §approvals, FR-052..057, clarify Q1).

The real human decision on a ``Backtesting -> Paper Trading`` recommendation. A deployment
recommendation opens a ``pending`` ``ApprovalRequest`` and leaves the strategy in
``PendingPaperApproval``; here a **SystemAdministrator** or **PortfolioManager** (only) approves
it into ``PaperTrading`` or rejects it (``reason`` required) into ``Deprecated``. Any other role
on approve/reject gets a 403 with an audited denial. No timeout ever auto-resolves a request
(FR-057). Paper -> Live is unchanged and stays behind ``POST /api/v1/strategies/{id}/promote``.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from src.api.deps import require_role
from src.core.db import get_session
from src.core.security import (
    ROLE_PORTFOLIO_MANAGER,
    ROLE_READ_ONLY_AUDITOR,
    ROLE_RISK_MANAGER,
    ROLE_SYSTEM_ADMINISTRATOR,
)
from src.models.approval import ApprovalRequest
from src.models.orchestration import ResultArtefact
from src.models.strategy import Strategy
from src.models.user import User
from src.orchestration import approvals as approvals_service
from src.orchestration.enums import ApprovalStatus

router = APIRouter(prefix="/api/v1/organization/approvals", tags=["approvals"])

# Reviewers (read); deciders (write) are SA/PM only per clarify Q1.
_can_view = require_role(
    ROLE_SYSTEM_ADMINISTRATOR,
    ROLE_PORTFOLIO_MANAGER,
    ROLE_RISK_MANAGER,
    ROLE_READ_ONLY_AUDITOR,
)
_can_decide = require_role(ROLE_SYSTEM_ADMINISTRATOR, ROLE_PORTFOLIO_MANAGER, audit_denials=True)


class ApprovalSummary(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID | None
    strategy_id: uuid.UUID
    strategy_version_id: uuid.UUID | None
    status: str
    decided_by: str | None
    decided_at: str | None
    reason: str | None
    created_at: str | None


class ArtefactRef(BaseModel):
    artefact_id: uuid.UUID
    artefact_type: str
    payload: dict[str, object]


class ApprovalDetail(ApprovalSummary):
    strategy_name: str | None
    strategy_status: str | None
    recommendation: ArtefactRef | None
    related_artefacts: list[ArtefactRef]
    # Full Go-Live review panel (backtest/optimisation/risk/compliance rollup) is rendered by the
    # Organization Command Center (US5); this endpoint returns the decision-critical fields.
    go_live_gate: dict[str, object] | None = None


class ApprovalRejectRequest(BaseModel):
    reason: str = Field(min_length=1)


def _summary(row: ApprovalRequest) -> ApprovalSummary:
    return ApprovalSummary(
        id=row.id,
        run_id=row.run_id,
        strategy_id=row.strategy_id,
        strategy_version_id=row.strategy_version_id,
        status=row.status,
        decided_by=row.decided_by,
        decided_at=row.decided_at.isoformat() if row.decided_at else None,
        reason=row.reason,
        created_at=row.created_at.isoformat() if row.created_at else None,
    )


@router.get("", response_model=list[ApprovalSummary])
def list_approvals(
    status: str = Query(default=ApprovalStatus.PENDING.value),
    _user: User = Depends(_can_view),
) -> list[ApprovalSummary]:
    with get_session() as session:
        rows = session.scalars(
            select(ApprovalRequest)
            .where(ApprovalRequest.status == status)
            .order_by(ApprovalRequest.created_at.asc())
        ).all()
        return [_summary(r) for r in rows]


@router.get("/{approval_id}", response_model=ApprovalDetail)
def get_approval(approval_id: uuid.UUID, _user: User = Depends(_can_view)) -> ApprovalDetail:
    with get_session() as session:
        row = session.get(ApprovalRequest, approval_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Approval request not found")
        strategy = session.get(Strategy, row.strategy_id)

        recommendation: ArtefactRef | None = None
        related: list[ArtefactRef] = []
        # ResultArtefacts only exist for org-led runs; the legacy graph path has none.
        if row.recommendation_artefact_id is not None:
            rec = session.get(ResultArtefact, row.recommendation_artefact_id)
            if rec is not None:
                recommendation = ArtefactRef(
                    artefact_id=rec.id,
                    artefact_type=rec.artefact_type,
                    payload=dict(rec.payload),
                )
        if row.run_id is not None:
            for a in session.scalars(
                select(ResultArtefact)
                .where(ResultArtefact.run_id == row.run_id)
                .order_by(ResultArtefact.created_at.asc())
            ).all():
                if recommendation is not None and a.id == recommendation.artefact_id:
                    continue
                related.append(
                    ArtefactRef(
                        artefact_id=a.id,
                        artefact_type=a.artefact_type,
                        payload=dict(a.payload),
                    )
                )

        base = _summary(row)
        return ApprovalDetail(
            **base.model_dump(),
            strategy_name=strategy.name if strategy is not None else None,
            strategy_status=strategy.status if strategy is not None else None,
            recommendation=recommendation,
            related_artefacts=related,
        )


@router.post("/{approval_id}/approve", response_model=ApprovalSummary)
def approve_approval(approval_id: uuid.UUID, user: User = Depends(_can_decide)) -> ApprovalSummary:
    with get_session() as session:
        try:
            row = approvals_service.approve(session, request_id=approval_id, actor_id=user.email)
        except approvals_service.ApprovalNotFoundError:
            raise HTTPException(status_code=404, detail="Approval request not found") from None
        except approvals_service.ApprovalAlreadyDecidedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        session.commit()
        session.refresh(row)
        return _summary(row)


@router.post("/{approval_id}/reject", response_model=ApprovalSummary)
def reject_approval(
    approval_id: uuid.UUID,
    body: ApprovalRejectRequest,
    user: User = Depends(_can_decide),
) -> ApprovalSummary:
    with get_session() as session:
        try:
            row = approvals_service.reject(
                session, request_id=approval_id, actor_id=user.email, reason=body.reason
            )
        except approvals_service.ApprovalNotFoundError:
            raise HTTPException(status_code=404, detail="Approval request not found") from None
        except approvals_service.ApprovalAlreadyDecidedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except approvals_service.RejectionReasonRequiredError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        session.commit()
        session.refresh(row)
        return _summary(row)
