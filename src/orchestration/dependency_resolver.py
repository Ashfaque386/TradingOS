"""Dependency resolution for the task engine (spec T032, data-model.md section 4,
FR-014/FR-015/FR-017).

- ``ready_tasks`` -- tasks whose every *hard* dependency is ``satisfied`` (and that are not
  already terminal). ``soft`` dependencies do not block readiness (FR-044).
- ``evaluate_on_completion`` -- when a task completes, mark the ``TaskDependency`` rows it
  satisfies, emit ``dependency.satisfied``, and flip newly-ready dependents from
  ``waiting_for_dependency`` back to ``ready``.
- ``mark_unsatisfiable`` -- when a prerequisite ends ``failed``/``blocked`` with no alternative
  producer, the dependent task is ``blocked`` with a clear reason (FR-017) -- never a false
  ``completed``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.orchestration import Task, TaskDependency
from src.orchestration import events
from src.orchestration.enums import DependencyState, TaskStatus

_TERMINAL_TASK_STATUSES = frozenset(
    {
        TaskStatus.COMPLETED.value,
        TaskStatus.FAILED.value,
        TaskStatus.BLOCKED.value,
        TaskStatus.CANCELLED.value,
        TaskStatus.SUPERSEDED.value,
    }
)


def _hard_deps_for(session: Session, task_id: uuid.UUID) -> list[TaskDependency]:
    return list(
        session.scalars(
            select(TaskDependency).where(
                TaskDependency.dependent_task_id == task_id,
                TaskDependency.policy == "hard",
            )
        ).all()
    )


def ready_tasks(session: Session, run_id: uuid.UUID) -> list[Task]:
    """Tasks eligible to run now: not terminal, not already running, and every hard dependency
    satisfied."""
    candidates = session.scalars(
        select(Task).where(
            Task.run_id == run_id,
            Task.status.in_(
                (
                    TaskStatus.PLANNED.value,
                    TaskStatus.QUEUED.value,
                    TaskStatus.READY.value,
                    TaskStatus.WAITING_FOR_DEPENDENCY.value,
                )
            ),
        )
    ).all()
    out: list[Task] = []
    for task in candidates:
        hard = _hard_deps_for(session, task.id)
        if all(d.state == DependencyState.SATISFIED.value for d in hard):
            if task.status != TaskStatus.READY.value:
                task.status = TaskStatus.READY.value
                events.emit(
                    session,
                    run_id=run_id,
                    event_type="task.ready",
                    subject_type="task",
                    subject_id=task.id,
                    payload={},
                )
            out.append(task)
        elif task.status != TaskStatus.WAITING_FOR_DEPENDENCY.value:
            task.status = TaskStatus.WAITING_FOR_DEPENDENCY.value
            waiting_on = next((d for d in hard if d.state != DependencyState.SATISFIED.value), None)
            events.emit(
                session,
                run_id=run_id,
                event_type="task.waiting_for_dependency",
                subject_type="task",
                subject_id=task.id,
                payload={
                    "waiting_for": waiting_on.required_artefact_type if waiting_on else None,
                    "owner_task_id": (str(waiting_on.prerequisite_task_id) if waiting_on else None),
                },
            )
    return out


def evaluate_on_completion(session: Session, completed_task: Task) -> None:
    """Mark dependencies this task satisfied and wake newly-ready dependents (FR-015)."""
    now = datetime.now(UTC)
    deps = session.scalars(
        select(TaskDependency).where(
            TaskDependency.prerequisite_task_id == completed_task.id,
            TaskDependency.state == DependencyState.UNSATISFIED.value,
        )
    ).all()
    for dep in deps:
        dep.state = DependencyState.SATISFIED.value
        dep.satisfied_at = now
        events.emit(
            session,
            run_id=completed_task.run_id,
            event_type="dependency.satisfied",
            subject_type="dependency",
            subject_id=dep.id,
            payload={
                "dependent_task_id": str(dep.dependent_task_id),
                "required_artefact_type": dep.required_artefact_type,
            },
        )
        dependent = session.get(Task, dep.dependent_task_id)
        if dependent is None or dependent.status in _TERMINAL_TASK_STATUSES:
            continue
        remaining = _hard_deps_for(session, dependent.id)
        if all(d.state == DependencyState.SATISFIED.value for d in remaining):
            dependent.status = TaskStatus.READY.value
            events.emit(
                session,
                run_id=completed_task.run_id,
                event_type="task.ready",
                subject_type="task",
                subject_id=dependent.id,
                payload={},
            )
    session.flush()


def mark_unsatisfiable(session: Session, prerequisite_task: Task, reason: str) -> None:
    """A prerequisite ended failed/blocked -- every dependent hard dependency fails and the
    dependent task is blocked with a clear reason (FR-017)."""
    deps = session.scalars(
        select(TaskDependency).where(
            TaskDependency.prerequisite_task_id == prerequisite_task.id,
            TaskDependency.policy == "hard",
            TaskDependency.state != DependencyState.SATISFIED.value,
        )
    ).all()
    for dep in deps:
        dep.state = DependencyState.FAILED.value
        events.emit(
            session,
            run_id=prerequisite_task.run_id,
            event_type="dependency.failed",
            subject_type="dependency",
            subject_id=dep.id,
            payload={"dependent_task_id": str(dep.dependent_task_id), "reason": reason},
            audited=True,
        )
        dependent = session.get(Task, dep.dependent_task_id)
        if dependent is None or dependent.status in _TERMINAL_TASK_STATUSES:
            continue
        dependent.status = TaskStatus.BLOCKED.value
        dependent.blocked_reason = f"prerequisite task '{prerequisite_task.capability}' {reason}"
        events.emit(
            session,
            run_id=prerequisite_task.run_id,
            event_type="task.blocked",
            subject_type="task",
            subject_id=dependent.id,
            payload={"blocked_reason": dependent.blocked_reason},
            audited=True,
        )
    session.flush()
