"""The real pre-Paper-Trading human approval gate (spec T048, FR-052..057, clarify Q1).

A deployment recommendation leaves the subject strategy in ``PendingPaperApproval`` and opens an
``ApprovalRequest``. This module performs the *decision*:

- ``approve`` -> ``Strategy.status: PendingPaperApproval -> PaperTrading``
- ``reject``  -> ``Strategy.status: PendingPaperApproval -> Deprecated`` (``reason`` required)

Every decision is written to the ``audit_log`` hash chain (actor + time) and, when the request
belongs to an ``OrganizationRun``, emits an organisation event and lets ``run_manager`` settle
the waiting run. There is deliberately **no timeout path** (FR-057): a request stays ``pending``
until a human with an allowed role decides it. RBAC (``SystemAdministrator`` /
``PortfolioManager`` only) is enforced at the router with an audited denial on any other role.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.audit import write_audit_entry
from src.models.approval import ApprovalRequest
from src.models.strategy import Strategy
from src.orchestration import events, run_manager
from src.orchestration.enums import ApprovalStatus

logger = structlog.get_logger(__name__)

_PENDING_PAPER = "PendingPaperApproval"
_PAPER_TRADING = "PaperTrading"
_DEPRECATED = "Deprecated"


class ApprovalNotFoundError(LookupError):
    """No ``ApprovalRequest`` with that id."""


class ApprovalAlreadyDecidedError(RuntimeError):
    """The request is not ``pending`` -- a decided request is never silently re-decided."""


class RejectionReasonRequiredError(ValueError):
    """FR-053: a rejection must carry a human-written reason."""


def has_approved_paper_request(session: Session, strategy_id: uuid.UUID) -> bool:
    """spec 002 US1 (closes the `/strategies/{id}/promote` bypass): the single enforcement
    point for whether a strategy may move to ``PaperTrading`` through *any* code path, not
    just the dedicated `approve()` above.

    True only when the most-recently-created `ApprovalRequest` for this strategy is
    ``approved``. A strategy with no request at all, one still `pending`, or whose latest
    request was `rejected`, all correctly return False -- a later rejection is never
    overridable by re-promoting through a different endpoint (spec 002 US1 AC1/AC2); an
    earlier approval still authorises promotion even after an unrelated status change
    elsewhere (AC3)."""
    latest = session.execute(
        select(ApprovalRequest)
        .where(ApprovalRequest.strategy_id == strategy_id)
        .order_by(ApprovalRequest.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return latest is not None and latest.status == ApprovalStatus.APPROVED.value


def _load_pending(session: Session, request_id: uuid.UUID) -> ApprovalRequest:
    request = session.get(ApprovalRequest, request_id)
    if request is None:
        raise ApprovalNotFoundError(str(request_id))
    if request.status != ApprovalStatus.PENDING.value:
        raise ApprovalAlreadyDecidedError(f"approval {request_id} is already '{request.status}'")
    return request


def approve(session: Session, *, request_id: uuid.UUID, actor_id: str) -> ApprovalRequest:
    """Record an allowed human's approval and move the strategy into Paper Trading."""
    request = _load_pending(session, request_id)
    now = datetime.now(UTC)

    strategy = session.get(Strategy, request.strategy_id)
    before_status = strategy.status if strategy is not None else None
    if strategy is not None and strategy.status == _PENDING_PAPER:
        strategy.status = _PAPER_TRADING

    request.status = ApprovalStatus.APPROVED.value
    request.decided_by = actor_id
    request.decided_at = now

    entry = write_audit_entry(
        session,
        actor_type="Human",
        actor_id=actor_id,
        action="APPROVAL_APPROVED",
        entity_type="ApprovalRequest",
        entity_id=request_id,
        before_state={"strategy_status": before_status},
        after_state={
            "strategy_id": str(request.strategy_id),
            "strategy_status": strategy.status if strategy is not None else None,
        },
    )
    request.audit_reference = entry.id

    if request.run_id is not None:
        events.emit(
            session,
            run_id=request.run_id,
            event_type="approval.approved",
            subject_type="approval",
            subject_id=request_id,
            payload={
                "strategy_id": str(request.strategy_id),
                "decided_by": actor_id,
                "reason": f"Approved by {actor_id}",
            },
        )
    session.flush()
    if request.run_id is not None:
        run_manager.settle_run_after_approval(session, request.run_id)
    logger.info("approval_approved", request_id=str(request_id), actor=actor_id)
    return request


def reject(
    session: Session, *, request_id: uuid.UUID, actor_id: str, reason: str
) -> ApprovalRequest:
    """Record an allowed human's rejection (``reason`` required) and deprecate the strategy."""
    if not reason or not reason.strip():
        raise RejectionReasonRequiredError("a rejection reason is required (FR-053)")
    request = _load_pending(session, request_id)
    now = datetime.now(UTC)

    strategy = session.get(Strategy, request.strategy_id)
    before_status = strategy.status if strategy is not None else None
    if strategy is not None and strategy.status == _PENDING_PAPER:
        strategy.status = _DEPRECATED

    request.status = ApprovalStatus.REJECTED.value
    request.decided_by = actor_id
    request.decided_at = now
    request.reason = reason.strip()

    entry = write_audit_entry(
        session,
        actor_type="Human",
        actor_id=actor_id,
        action="APPROVAL_REJECTED",
        entity_type="ApprovalRequest",
        entity_id=request_id,
        before_state={"strategy_status": before_status},
        after_state={
            "strategy_id": str(request.strategy_id),
            "strategy_status": strategy.status if strategy is not None else None,
            "reason": request.reason,
        },
    )
    request.audit_reference = entry.id

    if request.run_id is not None:
        events.emit(
            session,
            run_id=request.run_id,
            event_type="approval.rejected",
            subject_type="approval",
            subject_id=request_id,
            payload={
                "strategy_id": str(request.strategy_id),
                "decided_by": actor_id,
                "reason": f"Rejected by {actor_id}: {request.reason}",
            },
        )
    session.flush()
    if request.run_id is not None:
        run_manager.settle_run_after_approval(session, request.run_id)
    _remember_rejection(request, strategy, reason.strip())
    logger.info("approval_rejected", request_id=str(request_id), actor=actor_id)
    return request


def _remember_rejection(request: ApprovalRequest, strategy: Strategy | None, reason: str) -> None:
    """FR-033: a human rejection of a deployment recommendation is written to organisational
    memory so future planning can weigh why a similar strategy was turned down. Best-effort."""
    try:
        from src.memory.organization_memory import ingest_org_memory

        name = strategy.name if strategy is not None else str(request.strategy_id)
        ingest_org_memory(
            kind="rejected_strategy",
            text=f"Strategy '{name}' rejected at the Paper-Trading gate: {reason[:400]}",
            payload={
                "strategy_id": str(request.strategy_id),
                "approval_id": str(request.id),
                "reason": reason,
            },
        )
    except Exception as exc:  # noqa: BLE001 -- memory is best-effort
        logger.warning("org_rejection_memory_skipped", approval_id=str(request.id), error=str(exc))
