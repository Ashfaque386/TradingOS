"""Organisation run lifecycle (spec T017/T018, data-model.md section 1, research R3/R4).

``create_run`` inserts an ``OrganizationRun`` -- ``queued`` (with a real ``queue_position``) when
the concurrency cap is reached, else ``planning`` (FR-009 / clarify Q3). ``promote_queued`` fills
a freed slot oldest-first. ``reap_incomplete_runs`` (startup hook) re-enters non-terminal runs
after a restart (FR-019); a task left ``running`` at crash time is reset to ``ready`` (if its
capability is concurrency-safe / idempotent) or ``failed`` -- never a false ``completed``.

For this MVP increment the run reaches a validated plan and then parks in ``waiting`` -- the task
engine that executes the plan is the US2 phase (plan.md Phased Delivery).
"""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.core.config import get_settings
from src.core.db import get_session
from src.models.orchestration import OrganizationRun, Task
from src.models.tenant import DEFAULT_TENANT_ID
from src.orchestration import events
from src.orchestration.enums import RunSource, RunStatus, TaskStatus

logger = structlog.get_logger(__name__)

_ACTIVE_STATUSES = (
    RunStatus.PLANNING.value,
    RunStatus.RUNNING.value,
    RunStatus.WAITING.value,
    RunStatus.STALLED.value,
)


def _active_run_count(session: Session) -> int:
    return int(
        session.scalar(
            select(func.count(OrganizationRun.id)).where(
                OrganizationRun.status.in_(_ACTIVE_STATUSES)
            )
        )
        or 0
    )


def create_run(
    session: Session,
    *,
    objective: str,
    source: RunSource | str = RunSource.WEB,
    requested_by: str | None = None,
    tenant_id: uuid.UUID | str = DEFAULT_TENANT_ID,
    autostart: bool = True,
) -> OrganizationRun:
    """Insert an ``OrganizationRun`` and (if a slot is free) kick off planning in a detached
    thread. The caller owns the transaction up to the ``flush``; this commits before dispatching
    the thread so the row is visible to it."""
    cap = get_settings().org_max_concurrent_runs
    now = datetime.now(UTC)
    at_capacity = _active_run_count(session) >= cap
    queued_ahead = int(
        session.scalar(
            select(func.count(OrganizationRun.id)).where(
                OrganizationRun.status == RunStatus.QUEUED.value
            )
        )
        or 0
    )
    run = OrganizationRun(
        tenant_id=uuid.UUID(str(tenant_id)),
        objective=objective,
        source=str(source),
        requested_by=requested_by,
        status=RunStatus.QUEUED.value if at_capacity else RunStatus.PLANNING.value,
        queue_position=(queued_ahead + 1) if at_capacity else None,
        thread_id=f"org-{uuid.uuid4()}",
        created_at=now,
        updated_at=now,
    )
    session.add(run)
    session.flush()
    events.emit(
        session,
        run_id=run.id,
        event_type=("organization.run.queued" if at_capacity else "organization.run.planning"),
        subject_type="run",
        subject_id=run.id,
        payload={
            "objective": objective,
            "source": str(source),
            "queue_position": run.queue_position,
        },
        audited=True,
    )
    session.commit()

    if autostart and not at_capacity:
        _dispatch_planning(run.id)
    return run


def _dispatch_planning(run_id: uuid.UUID) -> None:
    threading.Thread(target=_plan_run, args=(run_id,), daemon=True).start()


def _plan_run(run_id: uuid.UUID) -> None:
    from src.orchestration.planner import generate_plan  # deferred: planner imports models/router

    try:
        with get_session() as session:
            run = session.get(OrganizationRun, run_id)
            if run is None or run.status != RunStatus.PLANNING.value:
                return
            generate_plan(session, run)
            # No task engine yet in this MVP increment -- a validated plan parks the run in
            # `waiting`; `cannot_plan` is set inside generate_plan on failure.
            session.refresh(run)
            if run.status == RunStatus.PLANNING.value:
                run.status = RunStatus.WAITING.value
                run.updated_at = datetime.now(UTC)
                events.emit(
                    session,
                    run_id=run.id,
                    event_type="organization.run.waiting",
                    subject_type="run",
                    subject_id=run.id,
                    payload={"note": "plan validated; task execution is the next phase"},
                )
            session.commit()
    except Exception as exc:  # noqa: BLE001 -- always close out the run row
        logger.error("organization_plan_run_failed", run_id=str(run_id), error=str(exc))
        with get_session() as session:
            run = session.get(OrganizationRun, run_id)
            if run is not None and run.status not in (
                RunStatus.CANNOT_PLAN.value,
                RunStatus.FAILED.value,
            ):
                run.status = RunStatus.FAILED.value
                run.ended_at = datetime.now(UTC)
                session.commit()


def promote_queued() -> None:
    """Fill any free concurrency slot with the oldest ``queued`` run (FR-009)."""
    with get_session() as session:
        cap = get_settings().org_max_concurrent_runs
        while _active_run_count(session) < cap:
            nxt = session.scalars(
                select(OrganizationRun)
                .where(OrganizationRun.status == RunStatus.QUEUED.value)
                .order_by(OrganizationRun.created_at.asc())
                .limit(1)
            ).first()
            if nxt is None:
                return
            nxt.status = RunStatus.PLANNING.value
            nxt.queue_position = None
            nxt.updated_at = datetime.now(UTC)
            session.commit()
            _dispatch_planning(nxt.id)


def reap_incomplete_runs() -> None:
    """Startup hook (FR-019). Any non-terminal run left over from a previous process is
    re-entered; a ``running`` task is reset to ``ready`` (concurrency-safe) or ``failed``."""
    from src.orchestration.capability_registry import is_concurrency_safe

    with get_session() as session:
        stuck_runs = session.scalars(
            select(OrganizationRun).where(OrganizationRun.status.in_(_ACTIVE_STATUSES))
        ).all()
        for run in stuck_runs:
            running_tasks = session.scalars(
                select(Task).where(Task.run_id == run.id, Task.status == TaskStatus.RUNNING.value)
            ).all()
            for task in running_tasks:
                if is_concurrency_safe(task.capability):
                    task.status = TaskStatus.READY.value
                    task.started_at = None
                else:
                    task.status = TaskStatus.FAILED.value
                    task.failure_reason = "process restarted mid-execution; not safely re-runnable"
            logger.info(
                "organization_run_reaped",
                run_id=str(run.id),
                status=run.status,
                reset_tasks=len(running_tasks),
            )
        session.commit()
    promote_queued()
