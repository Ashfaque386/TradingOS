"""Organisation run API (spec T028, contracts/rest-api.md).

MVP subset: create a run, list/inspect runs, read a run's plan, read a run's event stream. The
task / dependency / decision / approval / attention endpoints land with the US2+ phases.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from src.api.deps import get_current_user, require_role
from src.core.db import get_session
from src.core.security import (
    ROLE_PORTFOLIO_MANAGER,
    ROLE_RISK_MANAGER,
    ROLE_SYSTEM_ADMINISTRATOR,
)
from src.models.orchestration import (
    OrganizationalDecision,
    OrganizationalEvent,
    OrganizationalPlan,
    OrganizationRun,
    ResultArtefact,
    Task,
    TaskDependency,
)
from src.models.user import User
from src.orchestration import handoffs, run_manager
from src.orchestration.enums import RunSource, RunStatus, TaskStatus

router = APIRouter(prefix="/api/v1/organization", tags=["organization"])

_can_create_run = require_role(
    ROLE_SYSTEM_ADMINISTRATOR, ROLE_PORTFOLIO_MANAGER, ROLE_RISK_MANAGER, audit_denials=True
)


class CreateRunRequest(BaseModel):
    objective: str = Field(min_length=3)
    source: RunSource = RunSource.WEB


class RunSummary(BaseModel):
    run_id: uuid.UUID
    objective: str
    source: str
    status: str
    queue_position: int | None
    plan_id: uuid.UUID | None
    created_at: str


class PlannedTaskOut(BaseModel):
    task_id: uuid.UUID
    objective: str
    assigned_agent: str
    capability: str
    priority: int
    expected_output: str
    status: str
    is_concurrency_safe: bool
    depends_on: list[uuid.UUID]


class PlanOut(BaseModel):
    plan_id: uuid.UUID
    run_id: uuid.UUID
    objective_classification: str
    departments: list[str]
    approval_required: bool
    safety_requirements: dict[str, object]
    tasks: list[PlannedTaskOut]


class DecisionOut(BaseModel):
    decision_id: uuid.UUID
    decision_type: str
    summary: str
    reason: str
    next_step: str | None
    escalated_to_role: str | None
    resolved_by: str | None
    supporting_input_artefact_ids: list[str]
    created_at: str


class RunDetailOut(RunSummary):
    """The run workspace header (contracts/rest-api.md §runs): counts by task status, pending
    approvals, produced strategy, result summary."""

    ended_at: str | None
    task_counts: dict[str, int]
    pending_approvals: int
    produced_strategy_id: uuid.UUID | None
    result_summary: dict[str, object] | None
    dataset_freshness: dict[str, str]


class AttentionRunOut(BaseModel):
    run_id: uuid.UUID
    objective: str
    status: str
    stall_flagged_at: str | None


class AttentionTaskOut(BaseModel):
    task_id: uuid.UUID
    run_id: uuid.UUID
    capability: str
    assigned_agent: str
    status: str
    blocked_reason: str | None


class DatasetFreshnessOut(BaseModel):
    dataset_name: str
    cadence: str
    status: str
    last_successful_update: str | None
    last_checksum_ok: bool | None


class AttentionOut(BaseModel):
    stalled_runs: list[AttentionRunOut]
    blocked_tasks: list[AttentionTaskOut]
    escalated_decisions: list[DecisionOut]
    pending_approvals: int
    stale_datasets: list[DatasetFreshnessOut]


class ResolveDecisionRequest(BaseModel):
    note: str = Field(min_length=1)


class EventOut(BaseModel):
    sequence: int
    event_type: str
    subject_type: str
    subject_id: uuid.UUID | None
    payload: dict[str, object]
    occurred_at: str


@router.post("/runs", response_model=RunSummary, status_code=202)
def create_run(body: CreateRunRequest, _user: User = Depends(_can_create_run)) -> RunSummary:
    with get_session() as session:
        run = run_manager.create_run(
            session,
            objective=body.objective,
            source=body.source,
            requested_by=_user.email,
        )
        return RunSummary(
            run_id=run.id,
            objective=run.objective,
            source=run.source,
            status=run.status,
            queue_position=run.queue_position,
            plan_id=run.plan_id,
            created_at=run.created_at.isoformat(),
        )


@router.get("/runs", response_model=list[RunSummary])
def list_runs(
    status: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    _user: User = Depends(get_current_user),
) -> list[RunSummary]:
    """spec 002 US10: `offset` lets an operator page past the default cap instead of only ever
    seeing the most recent `limit` runs; `status` filtering (already real) composes with it
    server-side so the frontend never has to truncate client-side to fake a filtered page."""
    with get_session() as session:
        stmt = (
            select(OrganizationRun)
            .order_by(OrganizationRun.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        if status:
            stmt = stmt.where(OrganizationRun.status == status)
        return [
            RunSummary(
                run_id=r.id,
                objective=r.objective,
                source=r.source,
                status=r.status,
                queue_position=r.queue_position,
                plan_id=r.plan_id,
                created_at=r.created_at.isoformat(),
            )
            for r in session.scalars(stmt).all()
        ]


@router.get("/runs/{run_id}", response_model=RunDetailOut)
def get_run(run_id: uuid.UUID, _user: User = Depends(get_current_user)) -> RunDetailOut:
    from src.models.approval import ApprovalRequest
    from src.orchestration import freshness

    with get_session() as session:
        run = session.get(OrganizationRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        counts: dict[str, int] = {}
        for (task_status,) in session.execute(
            select(Task.status).where(Task.run_id == run_id)
        ).all():
            counts[task_status] = counts.get(task_status, 0) + 1
        pending = (
            session.scalar(
                select(func.count(ApprovalRequest.id)).where(
                    ApprovalRequest.run_id == run_id,
                    ApprovalRequest.status == "pending",
                )
            )
            or 0
        )
        required: set[str] = set()
        for (rd,) in session.execute(
            select(Task.required_datasets).where(Task.run_id == run_id)
        ).all():
            required.update(rd or [])
        all_freshness = {row["dataset_name"]: row["status"] for row in freshness.snapshot(session)}
        dataset_freshness = {d: all_freshness.get(d, "unavailable") for d in required}
        return RunDetailOut(
            run_id=run.id,
            objective=run.objective,
            source=run.source,
            status=run.status,
            queue_position=run.queue_position,
            plan_id=run.plan_id,
            created_at=run.created_at.isoformat(),
            ended_at=run.ended_at.isoformat() if run.ended_at else None,
            dataset_freshness=dataset_freshness,
            task_counts=counts,
            pending_approvals=int(pending),
            produced_strategy_id=run.produced_strategy_id,
            result_summary=dict(run.result_summary) if run.result_summary else None,
        )


@router.get("/runs/{run_id}/plan", response_model=PlanOut)
def get_plan(run_id: uuid.UUID, _user: User = Depends(get_current_user)) -> PlanOut:
    with get_session() as session:
        plan = session.scalars(
            select(OrganizationalPlan).where(OrganizationalPlan.run_id == run_id)
        ).first()
        if plan is None:
            raise HTTPException(status_code=404, detail="No plan for this run yet")
        tasks = session.scalars(select(Task).where(Task.plan_id == plan.id)).all()
        deps = session.scalars(
            select(TaskDependency).where(TaskDependency.plan_id == plan.id)
        ).all()
        dep_map: dict[uuid.UUID, list[uuid.UUID]] = {}
        for d in deps:
            dep_map.setdefault(d.dependent_task_id, []).append(d.prerequisite_task_id)
        return PlanOut(
            plan_id=plan.id,
            run_id=run_id,
            objective_classification=plan.objective_classification,
            departments=list(plan.departments),
            approval_required=plan.approval_required,
            safety_requirements=dict(plan.safety_requirements),
            tasks=[
                PlannedTaskOut(
                    task_id=t.id,
                    objective=t.objective,
                    assigned_agent=t.assigned_agent,
                    capability=t.capability,
                    priority=t.priority,
                    expected_output=t.expected_output,
                    status=t.status,
                    is_concurrency_safe=t.is_concurrency_safe,
                    depends_on=dep_map.get(t.id, []),
                )
                for t in tasks
            ],
        )


@router.get("/runs/{run_id}/decisions", response_model=list[DecisionOut])
def get_decisions(run_id: uuid.UUID, _user: User = Depends(get_current_user)) -> list[DecisionOut]:
    with get_session() as session:
        rows = session.scalars(
            select(OrganizationalDecision)
            .where(OrganizationalDecision.run_id == run_id)
            .order_by(OrganizationalDecision.created_at.asc())
        ).all()
        return [_decision_out(d) for d in rows]


def _decision_out(d: OrganizationalDecision) -> DecisionOut:
    return DecisionOut(
        decision_id=d.id,
        decision_type=d.decision_type,
        summary=d.summary,
        reason=d.reason,
        next_step=d.next_step,
        escalated_to_role=d.escalated_to_role,
        resolved_by=d.resolved_by,
        supporting_input_artefact_ids=list(d.supporting_input_artefact_ids),
        created_at=d.created_at.isoformat(),
    )


@router.get("/runs/{run_id}/events", response_model=list[EventOut])
def get_events(
    run_id: uuid.UUID,
    after_sequence: int = 0,
    _user: User = Depends(get_current_user),
) -> list[EventOut]:
    with get_session() as session:
        rows = session.scalars(
            select(OrganizationalEvent)
            .where(
                OrganizationalEvent.run_id == run_id,
                OrganizationalEvent.sequence > after_sequence,
            )
            .order_by(OrganizationalEvent.sequence.asc())
        ).all()
        return [
            EventOut(
                sequence=e.sequence,
                event_type=e.event_type,
                subject_type=e.subject_type,
                subject_id=e.subject_id,
                payload=dict(e.payload),
                occurred_at=e.occurred_at.isoformat(),
            )
            for e in rows
        ]


class HandoffOut(BaseModel):
    """spec 002 US3: a first-class, inspectable agent-to-agent artefact handoff -- sender,
    receiver, what was delivered, and (for a partially-satisfied consumer) what was expected
    but missing. Derived from real `ResultArtefact`/`Task` state, not a new stored entity."""

    from_task_id: uuid.UUID
    from_agent: str | None
    to_task_id: uuid.UUID
    to_agent: str | None
    artefact_id: uuid.UUID
    artefact_type: str
    delivered_at: str
    requested_but_missing: list[str]


@router.get("/runs/{run_id}/handoffs", response_model=list[HandoffOut])
def get_handoffs(run_id: uuid.UUID, _user: User = Depends(get_current_user)) -> list[HandoffOut]:
    with get_session() as session:
        rows = handoffs.list_handoffs(session, run_id)
        return [
            HandoffOut(
                from_task_id=uuid.UUID(h["from_task_id"]),
                from_agent=h["from_agent"],
                to_task_id=uuid.UUID(h["to_task_id"]),
                to_agent=h["to_agent"],
                artefact_id=uuid.UUID(h["artefact_id"]),
                artefact_type=h["artefact_type"],
                delivered_at=h["delivered_at"],
                requested_but_missing=h["requested_but_missing"],
            )
            for h in rows
        ]


class TaskOut(BaseModel):
    task_id: uuid.UUID
    objective: str
    assigned_agent: str
    capability: str
    priority: int
    status: str
    is_concurrency_safe: bool
    ran_concurrently: bool
    dependency_wait_seconds: int
    retry_count: int
    blocked_reason: str | None
    failure_reason: str | None
    result_artefact_id: uuid.UUID | None
    started_at: str | None
    completed_at: str | None
    depends_on: list[uuid.UUID]


class DependencyOut(BaseModel):
    dependent_task_id: uuid.UUID
    prerequisite_task_id: uuid.UUID
    required_artefact_type: str
    policy: str
    state: str
    satisfied_at: str | None


class ArtefactOut(BaseModel):
    artefact_id: uuid.UUID
    task_id: uuid.UUID
    artefact_type: str
    version: int
    disposition: str | None
    coverage: str | None
    provenance: dict[str, object]
    payload: dict[str, object]
    created_at: str


def _tasks_for_run(session, run_id: uuid.UUID) -> list[TaskOut]:  # type: ignore[no-untyped-def]
    tasks = session.scalars(select(Task).where(Task.run_id == run_id)).all()
    deps = (
        session.scalars(
            select(TaskDependency).where(
                TaskDependency.dependent_task_id.in_([t.id for t in tasks])
            )
        ).all()
        if tasks
        else []
    )
    dep_map: dict[uuid.UUID, list[uuid.UUID]] = {}
    for d in deps:
        dep_map.setdefault(d.dependent_task_id, []).append(d.prerequisite_task_id)
    return [
        TaskOut(
            task_id=t.id,
            objective=t.objective,
            assigned_agent=t.assigned_agent,
            capability=t.capability,
            priority=t.priority,
            status=t.status,
            is_concurrency_safe=t.is_concurrency_safe,
            ran_concurrently=t.ran_concurrently,
            dependency_wait_seconds=t.dependency_wait_seconds,
            retry_count=t.retry_count,
            blocked_reason=t.blocked_reason,
            failure_reason=t.failure_reason,
            result_artefact_id=t.result_artefact_id,
            started_at=t.started_at.isoformat() if t.started_at else None,
            completed_at=t.completed_at.isoformat() if t.completed_at else None,
            depends_on=dep_map.get(t.id, []),
        )
        for t in tasks
    ]


@router.get("/runs/{run_id}/tasks", response_model=list[TaskOut])
def get_tasks(run_id: uuid.UUID, _user: User = Depends(get_current_user)) -> list[TaskOut]:
    with get_session() as session:
        return _tasks_for_run(session, run_id)


@router.get("/runs/{run_id}/tasks/{task_id}", response_model=TaskOut)
def get_task(
    run_id: uuid.UUID, task_id: uuid.UUID, _user: User = Depends(get_current_user)
) -> TaskOut:
    with get_session() as session:
        for t in _tasks_for_run(session, run_id):
            if t.task_id == task_id:
                return t
    raise HTTPException(status_code=404, detail="Task not found")


@router.get("/runs/{run_id}/dependencies", response_model=list[DependencyOut])
def get_dependencies(
    run_id: uuid.UUID, _user: User = Depends(get_current_user)
) -> list[DependencyOut]:
    with get_session() as session:
        plan = session.scalars(
            select(OrganizationalPlan).where(OrganizationalPlan.run_id == run_id)
        ).first()
        if plan is None:
            return []
        rows = session.scalars(
            select(TaskDependency).where(TaskDependency.plan_id == plan.id)
        ).all()
        return [
            DependencyOut(
                dependent_task_id=d.dependent_task_id,
                prerequisite_task_id=d.prerequisite_task_id,
                required_artefact_type=d.required_artefact_type,
                policy=d.policy,
                state=d.state,
                satisfied_at=d.satisfied_at.isoformat() if d.satisfied_at else None,
            )
            for d in rows
        ]


@router.get("/runs/{run_id}/artefacts", response_model=list[ArtefactOut])
def get_artefacts(run_id: uuid.UUID, _user: User = Depends(get_current_user)) -> list[ArtefactOut]:
    with get_session() as session:
        rows = session.scalars(
            select(ResultArtefact)
            .where(ResultArtefact.run_id == run_id)
            .order_by(ResultArtefact.created_at.asc())
        ).all()
        return [
            ArtefactOut(
                artefact_id=a.id,
                task_id=a.task_id,
                artefact_type=a.artefact_type,
                version=a.version,
                disposition=a.disposition,
                coverage=a.coverage,
                provenance=dict(a.provenance),
                payload=dict(a.payload),
                created_at=a.created_at.isoformat(),
            )
            for a in rows
        ]


@router.post("/runs/{run_id}/cancel", response_model=RunSummary)
def cancel_run(run_id: uuid.UUID, _user: User = Depends(_can_create_run)) -> RunSummary:
    with get_session() as session:
        run = session.get(OrganizationRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        if run.status in (
            RunStatus.COMPLETED.value,
            RunStatus.FAILED.value,
            RunStatus.CANCELLED.value,
        ):
            raise HTTPException(status_code=409, detail=f"Run already {run.status}")
        run.status = RunStatus.CANCELLED.value
        session.query(Task).filter(
            Task.run_id == run_id,
            Task.status.notin_(
                (TaskStatus.COMPLETED.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value)
            ),
        ).update({Task.status: TaskStatus.CANCELLED.value}, synchronize_session=False)
        session.commit()
        return RunSummary(
            run_id=run.id,
            objective=run.objective,
            source=run.source,
            status=run.status,
            queue_position=run.queue_position,
            plan_id=run.plan_id,
            created_at=run.created_at.isoformat(),
        )


@router.get("/attention", response_model=AttentionOut)
def get_attention(_user: User = Depends(get_current_user)) -> AttentionOut:
    """Cross-run queue for the console home (FR-022, research R20): runs flagged ``stalled``,
    tasks ``blocked``/``escalated``, unresolved escalated decisions, and the pending-approval
    count."""
    from src.models.approval import ApprovalRequest
    from src.orchestration import freshness

    with get_session() as session:
        stalled = session.scalars(
            select(OrganizationRun)
            .where(OrganizationRun.status == RunStatus.STALLED.value)
            .order_by(OrganizationRun.updated_at.desc())
        ).all()
        stale = [row for row in freshness.snapshot(session) if row["status"] != "fresh"]
        blocked = session.scalars(
            select(Task)
            .where(Task.status.in_((TaskStatus.BLOCKED.value, TaskStatus.ESCALATED.value)))
            .order_by(Task.created_at.desc())
            .limit(100)
        ).all()
        escalated = session.scalars(
            select(OrganizationalDecision)
            .where(
                OrganizationalDecision.escalated_to_role.is_not(None),
                OrganizationalDecision.resolved_by.is_(None),
            )
            .order_by(OrganizationalDecision.created_at.desc())
            .limit(100)
        ).all()
        pending = (
            session.scalar(
                select(func.count(ApprovalRequest.id)).where(ApprovalRequest.status == "pending")
            )
            or 0
        )
        return AttentionOut(
            stalled_runs=[
                AttentionRunOut(
                    run_id=r.id,
                    objective=r.objective,
                    status=r.status,
                    stall_flagged_at=(
                        r.stall_flagged_at.isoformat() if r.stall_flagged_at else None
                    ),
                )
                for r in stalled
            ],
            blocked_tasks=[
                AttentionTaskOut(
                    task_id=t.id,
                    run_id=t.run_id,
                    capability=t.capability,
                    assigned_agent=t.assigned_agent,
                    status=t.status,
                    blocked_reason=t.blocked_reason,
                )
                for t in blocked
            ],
            escalated_decisions=[_decision_out(d) for d in escalated],
            pending_approvals=int(pending),
            stale_datasets=[
                DatasetFreshnessOut(
                    dataset_name=row["dataset_name"],
                    cadence=row["cadence"],
                    status=row["status"],
                    last_successful_update=row["last_successful_update"],
                    last_checksum_ok=row["last_checksum_ok"],
                )
                for row in stale
            ],
        )


@router.get("/freshness", response_model=list[DatasetFreshnessOut])
def get_freshness(_user: User = Depends(get_current_user)) -> list[DatasetFreshnessOut]:
    """Every tracked dataset's current freshness (T088/T089) -- the console's freshness panel."""
    from src.orchestration import freshness

    with get_session() as session:
        return [
            DatasetFreshnessOut(
                dataset_name=row["dataset_name"],
                cadence=row["cadence"],
                status=row["status"],
                last_successful_update=row["last_successful_update"],
                last_checksum_ok=row["last_checksum_ok"],
            )
            for row in freshness.snapshot(session)
        ]


@router.post("/decisions/{decision_id}/resolve", response_model=DecisionOut)
def resolve_decision(
    decision_id: uuid.UUID,
    body: ResolveDecisionRequest,
    user: User = Depends(_can_create_run),
) -> DecisionOut:
    """A human governance role records the resolution of an escalated conflict / decision
    (contracts/rest-api.md §attention). Sets ``resolved_by`` and writes an audit entry."""
    from src.core.audit import write_audit_entry

    with get_session() as session:
        decision = session.get(OrganizationalDecision, decision_id)
        if decision is None:
            raise HTTPException(status_code=404, detail="Decision not found")
        if decision.resolved_by is not None:
            raise HTTPException(status_code=409, detail="Decision already resolved")
        decision.resolved_by = user.email
        decision.next_step = (
            decision.next_step or ""
        ) + f"\n[resolved by {user.email}] {body.note}"
        write_audit_entry(
            session,
            actor_type="Human",
            actor_id=user.email,
            action="ORG_DECISION_RESOLVED",
            entity_type="OrganizationalDecision",
            entity_id=decision_id,
            after_state={"resolved_by": user.email, "note": body.note},
        )
        session.commit()
        session.refresh(decision)
        return _decision_out(decision)
