"""The task engine (spec T033/T034/T037/T038/T040, FR-013..FR-018, SC-001/SC-002).

``run_scheduler_loop`` drives one organisation run to completion: it repeatedly picks the ready
set (``dependency_resolver.ready_tasks``), runs concurrency-safe tasks in parallel on a bounded
``ThreadPoolExecutor`` and everything else one at a time, and stops when no task can make
further progress. Each task is claimed with a Postgres advisory lock + a conditional
``UPDATE ... WHERE status='ready'`` so two run workers can never double-claim it (research R2).

Task status, run status, agent status and approval status stay distinct concepts (FR-012).
"""

from __future__ import annotations

import concurrent.futures
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from src.core.config import get_settings
from src.core.db import get_session
from src.models.orchestration import OrganizationRun, Task
from src.orchestration import agent_invoker, artefact_store, dependency_resolver, events
from src.orchestration.enums import RunStatus, TaskStatus

logger = structlog.get_logger(__name__)


def _as_utc(value: datetime | None) -> datetime | None:
    """The organisation tables store naive UTC timestamps; make one comparable with an
    ``aware`` ``datetime.now(UTC)`` without changing the wall-clock value."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


_NONTERMINAL = (
    TaskStatus.CREATED.value,
    TaskStatus.PLANNED.value,
    TaskStatus.QUEUED.value,
    TaskStatus.READY.value,
    TaskStatus.RUNNING.value,
    TaskStatus.WAITING_FOR_DEPENDENCY.value,
    TaskStatus.WAITING_FOR_AGENT.value,
    TaskStatus.RETRYING.value,
)


def run_scheduler_loop(run_id: uuid.UUID) -> None:
    """Synchronous end-to-end (matches the detached-thread execution model already used by the
    research graph). Returns when the run is terminal or fully stalled."""
    pool_size = get_settings().org_task_pool_size
    with get_session() as session:
        run = session.get(OrganizationRun, run_id)
        if run is None:
            return
        run.status = RunStatus.RUNNING.value
        run.started_at = run.started_at or datetime.now(UTC)
        events.emit(
            session,
            run_id=run_id,
            event_type="organization.run.running",
            subject_type="run",
            subject_id=run_id,
            payload={},
        )
        session.commit()

    while True:
        with get_session() as session:
            ready = dependency_resolver.ready_tasks(session, run_id)
            ready_ids = [(t.id, t.is_concurrency_safe) for t in ready]
            session.commit()

        if not ready_ids:
            if _finalize(run_id):
                return
            # Nothing ready and not finalizable -> everything left is blocked/waiting on a
            # failed prerequisite; finalize will have marked the run failed. Guard against a
            # hot loop.
            return

        safe = [tid for tid, is_safe in ready_ids if is_safe]
        unsafe = [tid for tid, is_safe in ready_ids if not is_safe]

        if safe:
            with concurrent.futures.ThreadPoolExecutor(max_workers=pool_size) as pool:
                list(pool.map(lambda tid: _execute_task(run_id, tid), safe))
        for tid in unsafe:
            _execute_task(run_id, tid)


def _execute_task(run_id: uuid.UUID, task_id: uuid.UUID) -> None:
    # --- claim (advisory lock + conditional update: exactly one worker wins) ---
    with get_session() as session:
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"task:{task_id}"}
        )
        claimed = session.execute(
            text(
                "UPDATE tasks SET status = :running, started_at = now() "
                "WHERE id = :id AND status = :ready RETURNING id"
            ),
            {
                "running": TaskStatus.RUNNING.value,
                "ready": TaskStatus.READY.value,
                "id": str(task_id),
            },
        ).first()
        if claimed is None:
            session.commit()
            return
        task = session.get(Task, task_id)
        assert task is not None
        events.emit(
            session,
            run_id=run_id,
            event_type="task.started",
            subject_type="task",
            subject_id=task_id,
            payload={"assigned_agent": task.assigned_agent, "capability": task.capability},
        )
        session.commit()

    # --- run ---
    try:
        with get_session() as session:
            task = session.get(Task, task_id)
            assert task is not None
            agent_invoker.dispatch(session, task)
            now = datetime.now(UTC)
            task.status = TaskStatus.COMPLETED.value
            task.completed_at = now
            started = _as_utc(task.started_at)
            events.emit(
                session,
                run_id=run_id,
                event_type="task.completed",
                subject_type="task",
                subject_id=task_id,
                payload={
                    "result_artefact_id": str(task.result_artefact_id),
                    "duration_seconds": ((now - started).total_seconds() if started else None),
                },
            )
            dependency_resolver.evaluate_on_completion(session, task)
            session.commit()
    except Exception as exc:  # noqa: BLE001 -- classify -> retry or fail; never leave 'running'
        logger.warning(
            "org_task_execution_error",
            task_id=str(task_id),
            error=str(exc),
            error_type=type(exc).__name__,
        )
        _handle_task_failure(run_id, task_id, exc)


def _handle_task_failure(run_id: uuid.UUID, task_id: uuid.UUID, exc: Exception) -> None:
    with get_session() as session:
        task = session.get(Task, task_id)
        if task is None:
            return
        if task.retry_count < task.max_retries:
            task.retry_count += 1
            task.status = TaskStatus.READY.value
            task.started_at = None
            events.emit(
                session,
                run_id=run_id,
                event_type="task.retrying",
                subject_type="task",
                subject_id=task_id,
                payload={"attempt": task.retry_count, "error": str(exc)},
            )
            session.commit()
            return
        task.status = TaskStatus.FAILED.value
        task.failure_reason = str(exc)
        task.completed_at = datetime.now(UTC)
        events.emit(
            session,
            run_id=run_id,
            event_type="task.failed",
            subject_type="task",
            subject_id=task_id,
            payload={"failure_reason": str(exc), "retry_count": task.retry_count},
            audited=True,
        )
        dependency_resolver.mark_unsatisfiable(session, task, "failed after exhausting retries")
        session.commit()


def _has_pending_approval(session: Session, run_id: uuid.UUID) -> bool:
    from src.orchestration.run_manager import has_pending_approval

    return has_pending_approval(session, run_id)


def _finalize(run_id: uuid.UUID) -> bool:
    """Returns True if the run reached a terminal state. Sets ``dependency_wait_seconds`` /
    ``ran_concurrently`` on the tasks and blocks completion while any artefact is
    undispositioned (SC-004)."""
    with get_session() as session:
        run = session.get(OrganizationRun, run_id)
        if run is None:
            return True
        nonterminal = session.scalar(
            select(func.count(Task.id)).where(Task.run_id == run_id, Task.status.in_(_NONTERMINAL))
        )
        if nonterminal:
            # tasks still runnable/waiting -> keep looping
            if session.scalar(
                select(func.count(Task.id)).where(
                    Task.run_id == run_id, Task.status == TaskStatus.READY.value
                )
            ):
                return False
            run.status = RunStatus.WAITING.value
            run.updated_at = datetime.now(UTC)
            session.commit()
            return False

        tasks = list(session.scalars(select(Task).where(Task.run_id == run_id)).all())
        _record_timings(session, tasks)

        failed = [t for t in tasks if t.status == TaskStatus.FAILED.value]
        blocked = [t for t in tasks if t.status == TaskStatus.BLOCKED.value]
        undispositioned = artefact_store.undispositioned_count(session, run_id=run_id)
        now = datetime.now(UTC)
        if failed or blocked:
            run.status = RunStatus.FAILED.value
            run.ended_at = now
            run.result_summary = {
                "failed_tasks": len(failed),
                "blocked_tasks": len(blocked),
            }
            events.emit(
                session,
                run_id=run_id,
                event_type="organization.run.failed",
                subject_type="run",
                subject_id=run_id,
                payload=run.result_summary,
                audited=True,
            )
        elif undispositioned:
            # Every artefact must be consumed or explicitly informational before a run can
            # complete (SC-004). MVP: artefacts are persisted as `informational`, so this is
            # normally 0; guard anyway.
            run.status = RunStatus.WAITING.value
            session.commit()
            return False
        elif _has_pending_approval(session, run_id):
            # FR-052 (US3): a run that produced an ApprovalRequest parks in `waiting` until a
            # human with an allowed role decides it -- `approvals.settle_run_after_approval`
            # then completes the run. No timeout auto-resolves it (FR-057).
            run.status = RunStatus.WAITING.value
            run.updated_at = now
            session.commit()
            return False
        else:
            run.status = RunStatus.COMPLETED.value
            run.ended_at = now
            run.result_summary = {"completed_tasks": len(tasks)}
            events.emit(
                session,
                run_id=run_id,
                event_type="organization.run.completed",
                subject_type="run",
                subject_id=run_id,
                payload=run.result_summary,
                audited=True,
            )
        session.commit()
        return True


def _record_timings(session: Session, tasks: list[Task]) -> None:
    """FR-016: mark ``ran_concurrently`` (window overlaps a sibling) and
    ``dependency_wait_seconds`` (start minus latest prerequisite completion)."""
    from src.models.orchestration import TaskDependency

    windows = [
        (t, t.started_at, t.completed_at)
        for t in tasks
        if t.started_at is not None and t.completed_at is not None
    ]
    for t in tasks:
        if t.started_at is None or t.completed_at is None:
            continue
        overlaps = any(
            other is not t and s < t.completed_at and t.started_at < e for other, s, e in windows
        )
        t.ran_concurrently = overlaps
        prereq_ids = list(
            session.scalars(
                select(TaskDependency.prerequisite_task_id).where(
                    TaskDependency.dependent_task_id == t.id
                )
            ).all()
        )
        if prereq_ids:
            latest = session.scalar(
                select(func.max(Task.completed_at)).where(Task.id.in_(prereq_ids))
            )
            if latest is not None:
                t.dependency_wait_seconds = max(0, int((t.started_at - latest).total_seconds()))
    session.flush()
