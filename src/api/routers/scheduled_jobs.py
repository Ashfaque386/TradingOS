"""REL-081: in-app scheduled-jobs control surface, replacing the 4 Windows Scheduled Tasks
confirmed unreliable this session (`Get-ScheduledTaskInfo` showed real launch/kill failures on
all 4 -- `0x41306`/`0x800710E0`/`0xC000013A`/a generic `1` -- and `LogonType=Interactive` only
firing within an active desktop session).

  - GET  /scheduled-jobs                  -- every job in src.agents.scheduler.JOB_REGISTRY, its
    effective schedule, live/computed next-run time, and its most recent execution.
  - GET  /scheduled-jobs/{job_id}         -- one job's full detail.
  - GET  /scheduled-jobs/{job_id}/history -- that job's real execution ledger, paginated.
  - PUT  /scheduled-jobs/{job_id}         -- edit its cron/enabled state; re-applied to the LIVE
    scheduler immediately (src.agents.scheduler.apply_schedule_change), not just on next restart.
  - POST /scheduled-jobs/{job_id}/run-now -- dispatch a real, tracked, out-of-cycle run on the
    live scheduler (src.agents.scheduler.dispatch_manual_run) -- the exact same executor and
    async/sync handling a real cron fire uses, just firing once, now.

See src/agents/scheduler.py's own module docstring for the architecture decisions (why no
persistent APScheduler job store, why Run Now reuses the live instance instead of a second
dispatch mechanism).
"""

from datetime import UTC, datetime

import structlog
from apscheduler.triggers.cron import CronTrigger
from cron_descriptor import Options, get_description
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.agents.scheduler import (
    IST_TIMEZONE,
    JOB_REGISTRY,
    apply_schedule_change,
    dispatch_manual_run,
    get_effective_schedule,
    get_running_scheduler,
    validate_cron_expression,
)
from src.api.deps import require_role
from src.core.audit import write_audit_entry
from src.core.db import get_session
from src.core.security import (
    ROLE_PORTFOLIO_MANAGER,
    ROLE_READ_ONLY_AUDITOR,
    ROLE_RISK_MANAGER,
    ROLE_SYSTEM_ADMINISTRATOR,
)
from src.models.scheduled_job import ScheduledJobRun
from src.models.user import User

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/scheduled-jobs", tags=["scheduled-jobs"])

# REL-081: reads are broadened to PM/RM/Auditor -- status/history visibility, not control -- a
# deliberately broader set than audit.py's own SA+Auditor-only `_can_read_audit` pattern (this
# data is less sensitive than raw audit-log content), not a direct copy of it. Mutations
# (PUT, Run Now) were initially scoped SA-only (matching `_can_manage_llm_keys`/broker credential
# management, on the reasoning that 3 of the 4 newly-internalized jobs are compliance/infra
# functions), then broadened to SA/PM/RM after live use showed the SA-only gate silently hid
# every mutating control for a PM/RM viewer with no explanation -- now matches
# `_can_manage_hitl`'s own precedent for `PUT /agents/control/{agent_name}`: a schedule edit is
# an equivalent-weight operational action, not a compliance-tier one.
_can_view_scheduled_jobs = require_role(
    ROLE_SYSTEM_ADMINISTRATOR,
    ROLE_READ_ONLY_AUDITOR,
    ROLE_PORTFOLIO_MANAGER,
    ROLE_RISK_MANAGER,
    audit_denials=True,
)
_can_manage_scheduled_jobs = require_role(
    ROLE_SYSTEM_ADMINISTRATOR, ROLE_PORTFOLIO_MANAGER, ROLE_RISK_MANAGER, audit_denials=True
)


class ScheduledJobRunEntry(BaseModel):
    id: str
    trigger_source: str
    status: str
    started_at: datetime
    ended_at: datetime | None
    result_summary: str | None
    triggered_by: str | None


class ScheduledJobSummary(BaseModel):
    job_id: str
    display_name: str
    description: str
    is_new: bool
    cron_expression: str
    human_readable: str
    default_cron_expression: str
    enabled: bool
    next_run_time: datetime | None
    last_run: ScheduledJobRunEntry | None


class ScheduledJobDetail(ScheduledJobSummary):
    pass


class UpdateScheduledJobRequest(BaseModel):
    cron_expression: str | None = None
    enabled: bool | None = None


class RunNowResponse(BaseModel):
    job_run_id: str
    status: str


# REL-081: the 4 jobs previously driven by external Windows Scheduled Tasks -- everything else
# in JOB_REGISTRY was already running in-process before this release, just with no schedule/
# history visibility. Drives ScheduledJobSummary.is_new.
_FORMERLY_EXTERNAL_JOB_IDS = frozenset(
    {
        "scheduler_shadow_mode_daily_cycle",
        "scheduler_audit_archive",
        "scheduler_audit_chain_verification",
        "scheduler_data_lake_backup",
    }
)


def _human_readable(cron_expression: str) -> str:
    """`cron_descriptor` since an admin can `PUT` arbitrary cron via this API, not just the 11
    known job shapes -- a hand-rolled describer would have to become a real generic cron parser
    anyway. Its own parser is independent of APScheduler's `CronTrigger.from_crontab` (already
    validated by the caller), so a genuinely odd-but-valid expression it can't describe falls
    back to the raw string rather than 500ing the whole response."""
    try:
        return str(get_description(cron_expression, Options()))
    except Exception:  # noqa: BLE001 -- a description failure must never break the API response
        return cron_expression


def _next_run_time(job_id: str, cron_expression: str) -> datetime | None:
    """The live scheduler's own `next_run_time` when this process actually has one running
    (`get_running_scheduler()` is not `None`) -- otherwise (the `app-tls` sibling, which never
    starts a scheduler by design, REL-007 E7.6) a computed fallback from the effective cron
    itself, so the field is never dishonestly blank just because this specific process isn't the
    one that fires it."""
    scheduler = get_running_scheduler()
    if scheduler is not None:
        job = scheduler.get_job(job_id)
        return job.next_run_time if job is not None else None
    trigger = CronTrigger.from_crontab(cron_expression, timezone=IST_TIMEZONE)
    next_fire_time: datetime | None = trigger.get_next_fire_time(None, datetime.now(UTC))
    return next_fire_time


def _most_recent_run(session: Session, job_id: str) -> ScheduledJobRunEntry | None:
    row = session.scalar(
        select(ScheduledJobRun)
        .where(ScheduledJobRun.job_id == job_id)
        .order_by(ScheduledJobRun.started_at.desc())
        .limit(1)
    )
    if row is None:
        return None
    return _to_run_entry(session, row)


def _to_run_entry(session: Session, row: ScheduledJobRun) -> ScheduledJobRunEntry:
    triggered_by_email = None
    if row.triggered_by_user_id is not None:
        user = session.get(User, row.triggered_by_user_id)
        triggered_by_email = user.email if user is not None else None
    return ScheduledJobRunEntry(
        id=str(row.id),
        trigger_source=row.trigger_source,
        status=row.status,
        started_at=row.started_at,
        ended_at=row.ended_at,
        result_summary=row.result_summary,
        triggered_by=triggered_by_email,
    )


def _build_summary(session: Session, job_id: str) -> ScheduledJobSummary:
    spec = JOB_REGISTRY[job_id]
    cron_expression, enabled = get_effective_schedule(job_id, session=session)
    return ScheduledJobSummary(
        job_id=job_id,
        display_name=spec.display_name,
        description=spec.description,
        is_new=job_id in _FORMERLY_EXTERNAL_JOB_IDS,
        cron_expression=cron_expression,
        human_readable=_human_readable(cron_expression),
        default_cron_expression=spec.default_cron,
        enabled=enabled,
        next_run_time=_next_run_time(job_id, cron_expression) if enabled else None,
        last_run=_most_recent_run(session, job_id),
    )


@router.get("", response_model=list[ScheduledJobSummary])
def list_scheduled_jobs(
    user: User = Depends(_can_view_scheduled_jobs),
) -> list[ScheduledJobSummary]:
    with get_session() as session:
        return [_build_summary(session, job_id) for job_id in JOB_REGISTRY]


@router.get("/{job_id}", response_model=ScheduledJobDetail)
def get_scheduled_job(
    job_id: str, user: User = Depends(_can_view_scheduled_jobs)
) -> ScheduledJobDetail:
    if job_id not in JOB_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Unknown scheduled job '{job_id}'")
    with get_session() as session:
        summary = _build_summary(session, job_id)
    return ScheduledJobDetail(**summary.model_dump())


@router.get("/{job_id}/history", response_model=list[ScheduledJobRunEntry])
def get_scheduled_job_history(
    job_id: str,
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(_can_view_scheduled_jobs),
) -> list[ScheduledJobRunEntry]:
    if job_id not in JOB_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Unknown scheduled job '{job_id}'")
    with get_session() as session:
        rows = session.scalars(
            select(ScheduledJobRun)
            .where(ScheduledJobRun.job_id == job_id)
            .order_by(ScheduledJobRun.started_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return [_to_run_entry(session, row) for row in rows]


@router.put("/{job_id}", response_model=ScheduledJobSummary)
def update_scheduled_job(
    job_id: str,
    body: UpdateScheduledJobRequest,
    user: User = Depends(_can_manage_scheduled_jobs),
) -> ScheduledJobSummary:
    """Edits the real schedule and re-applies it to the LIVE scheduler immediately -- see
    `src.agents.scheduler.apply_schedule_change`'s own docstring. Audited the same way every
    other admin-consequential mutation in this codebase is (write_audit_entry)."""
    if job_id not in JOB_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Unknown scheduled job '{job_id}'")
    if body.cron_expression is not None and not validate_cron_expression(body.cron_expression):
        raise HTTPException(
            status_code=400,
            detail=f"'{body.cron_expression}' is not a valid 5-field cron expression",
        )
    if body.cron_expression is None and body.enabled is None:
        raise HTTPException(status_code=400, detail="Provide cron_expression and/or enabled")

    apply_schedule_change(
        job_id,
        cron_expression=body.cron_expression,
        enabled=body.enabled,
        updated_by_user_id=user.id,
    )
    with get_session() as session:
        write_audit_entry(
            session,
            actor_type="Human",
            actor_id=str(user.id),
            action="SCHEDULED_JOB_CONFIG_CHANGED",
            entity_type="ScheduledJobConfig",
            after_state={
                "job_id": job_id,
                "cron_expression": body.cron_expression,
                "enabled": body.enabled,
            },
            prompt_snapshot=f"Updated schedule for {job_id}",
        )
        session.commit()
        summary = _build_summary(session, job_id)
    return summary


@router.post("/{job_id}/run-now", response_model=RunNowResponse, status_code=202)
def run_scheduled_job_now(
    job_id: str, user: User = Depends(_can_manage_scheduled_jobs)
) -> RunNowResponse:
    """Dispatches a real, tracked, out-of-cycle run on the live scheduler -- see
    `src.agents.scheduler.dispatch_manual_run`'s own docstring. Returns immediately with a real
    `job_run_id` the frontend polls via `GET .../history`; a `503` means no scheduler is running
    on this process (true today only for the `app-tls` sibling, `RUN_SCHEDULER=false` by design)."""
    if job_id not in JOB_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Unknown scheduled job '{job_id}'")
    run_id = dispatch_manual_run(job_id, triggered_by_user_id=user.id)
    if run_id is None:
        raise HTTPException(
            status_code=503, detail="No scheduler is running on this process for Run Now to use."
        )
    with get_session() as session:
        write_audit_entry(
            session,
            actor_type="Human",
            actor_id=str(user.id),
            action="SCHEDULED_JOB_RUN_NOW",
            entity_type="ScheduledJobRun",
            entity_id=run_id,
            after_state={"job_id": job_id},
            prompt_snapshot=f"Manually ran {job_id}",
        )
        session.commit()
    return RunNowResponse(job_run_id=str(run_id), status="Running")
