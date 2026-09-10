"""Organisation run API (spec T028, contracts/rest-api.md).

MVP subset: create a run, list/inspect runs, read a run's plan, read a run's event stream. The
task / dependency / decision / approval / attention endpoints land with the US2+ phases.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

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
from src.orchestration import run_manager
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
    decision_type: str
    summary: str
    reason: str
    next_step: str | None
    created_at: str


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
    _user: User = Depends(get_current_user),
) -> list[RunSummary]:
    with get_session() as session:
        stmt = select(OrganizationRun).order_by(OrganizationRun.created_at.desc()).limit(limit)
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


@router.get("/runs/{run_id}", response_model=RunSummary)
def get_run(run_id: uuid.UUID, _user: User = Depends(get_current_user)) -> RunSummary:
    with get_session() as session:
        run = session.get(OrganizationRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return RunSummary(
            run_id=run.id,
            objective=run.objective,
            source=run.source,
            status=run.status,
            queue_position=run.queue_position,
            plan_id=run.plan_id,
            created_at=run.created_at.isoformat(),
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
        return [
            DecisionOut(
                decision_type=d.decision_type,
                summary=d.summary,
                reason=d.reason,
                next_step=d.next_step,
                created_at=d.created_at.isoformat(),
            )
            for d in rows
        ]


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
