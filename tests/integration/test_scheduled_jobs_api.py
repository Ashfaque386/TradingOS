"""REL-081: /api/v1/scheduled-jobs integration tests against the real FastAPI app + real
Postgres `scheduled_job_config`/`scheduled_job_run` tables.

No test in this file (or anywhere in this codebase, confirmed by grep -- nothing uses
`with TestClient(app) as client:`) ever runs `src.api.main`'s `lifespan`, so `build_scheduler()`
never runs and `get_running_scheduler()` is `None` for the whole suite by default -- exactly the
same real state `app-tls` is in by design (`RUN_SCHEDULER=false`). Tests that need a live
scheduler build one directly and monkeypatch it onto `src.agents.scheduler._scheduler_instance`,
mirroring `test_scheduler.py`'s own `build_scheduler()`-in-test pattern.
"""

import uuid

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi.testclient import TestClient

import src.agents.scheduler as scheduler_module
from src.api.main import app
from src.core.db import get_session
from src.core.security import (
    ROLE_PORTFOLIO_MANAGER,
    ROLE_READ_ONLY_AUDITOR,
    ROLE_RISK_MANAGER,
    ROLE_SYSTEM_ADMINISTRATOR,
)
from src.models.scheduled_job import ScheduledJobConfig, ScheduledJobRun
from tests.auth_helpers import auth_header, cleanup_user, create_authenticated_user

client = TestClient(app)

_JOB_ID = scheduler_module.MARKET_DATA_INGESTION_JOB_ID  # a real, stable, pre-existing job ID


@pytest.fixture(autouse=True)
def _reset_live_scheduler_global():
    """Every test in this module (and `test_scheduler.py`, which also calls `build_scheduler()`)
    shares the same process-wide `src.agents.scheduler._scheduler_instance` global -- without
    this, one test's `build_scheduler()` call would leak a real (if unstarted) scheduler into a
    later test's `get_running_scheduler()` call, regardless of file/test order."""
    scheduler_module._scheduler_instance = None
    yield
    scheduler_module._scheduler_instance = None


def _cleanup_config_row(job_id: str) -> None:
    with get_session() as session:
        session.query(ScheduledJobConfig).filter(ScheduledJobConfig.job_id == job_id).delete()
        session.commit()


def _cleanup_run_rows(job_id: str) -> None:
    with get_session() as session:
        session.query(ScheduledJobRun).filter(ScheduledJobRun.job_id == job_id).delete()
        session.commit()


def test_list_returns_every_real_registered_job_with_defaults():
    user_id, token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        response = client.get("/api/v1/scheduled-jobs", headers=auth_header(token))
        assert response.status_code == 200
        body = {entry["job_id"]: entry for entry in response.json()}
        assert len(body) == len(scheduler_module.JOB_REGISTRY)
        entry = body[_JOB_ID]
        assert entry["enabled"] is True
        assert entry["is_new"] is False
        assert entry["cron_expression"] == entry["default_cron_expression"]
        assert entry["last_run"] is None
        # Newly-internalized jobs are flagged honestly so the frontend can badge them.
        assert body[scheduler_module.SHADOW_MODE_DAILY_CYCLE_JOB_ID]["is_new"] is True
        assert body[scheduler_module.AUDIT_ARCHIVE_JOB_ID]["is_new"] is True
        assert body[scheduler_module.AUDIT_CHAIN_VERIFICATION_JOB_ID]["is_new"] is True
        assert body[scheduler_module.DATA_LAKE_BACKUP_JOB_ID]["is_new"] is True
    finally:
        cleanup_user(user_id)


@pytest.mark.parametrize(
    "role",
    [ROLE_SYSTEM_ADMINISTRATOR, ROLE_READ_ONLY_AUDITOR, ROLE_PORTFOLIO_MANAGER, ROLE_RISK_MANAGER],
)
def test_every_real_role_can_view(role):
    """All 4 real roles can view -- there is no excluded role for this route (unlike every
    mutation route below), matching src.core.security.ALL_ROLES having exactly these 4."""
    user_id, token = create_authenticated_user(role)
    try:
        response = client.get("/api/v1/scheduled-jobs", headers=auth_header(token))
        assert response.status_code == 200
    finally:
        cleanup_user(user_id)


def test_get_detail_unknown_job_id_is_a_real_404():
    user_id, token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        response = client.get(
            f"/api/v1/scheduled-jobs/not-a-real-job-{uuid.uuid4().hex[:8]}",
            headers=auth_header(token),
        )
        assert response.status_code == 404
    finally:
        cleanup_user(user_id)


def test_get_history_unknown_job_id_is_a_real_404():
    user_id, token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        response = client.get(
            f"/api/v1/scheduled-jobs/not-a-real-job-{uuid.uuid4().hex[:8]}/history",
            headers=auth_header(token),
        )
        assert response.status_code == 404
    finally:
        cleanup_user(user_id)


def test_history_is_paginated_and_ordered_most_recent_first():
    from datetime import UTC, datetime, timedelta

    with get_session() as session:
        base = datetime.now(UTC)
        for i in range(3):
            session.add(
                ScheduledJobRun(
                    job_id=_JOB_ID,
                    trigger_source="cron",
                    status="Completed",
                    started_at=base - timedelta(minutes=i),
                    ended_at=base - timedelta(minutes=i) + timedelta(seconds=5),
                    result_summary=f"run {i}",
                )
            )
        session.commit()

    user_id, token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        response = client.get(
            f"/api/v1/scheduled-jobs/{_JOB_ID}/history?limit=2&offset=0",
            headers=auth_header(token),
        )
        assert response.status_code == 200
        page1 = response.json()
        assert len(page1) == 2
        assert page1[0]["result_summary"] == "run 0"  # most recent first

        page2 = client.get(
            f"/api/v1/scheduled-jobs/{_JOB_ID}/history?limit=2&offset=2",
            headers=auth_header(token),
        ).json()
        assert len(page2) == 1
        assert page2[0]["result_summary"] == "run 2"
    finally:
        cleanup_user(user_id)
        _cleanup_run_rows(_JOB_ID)


def test_put_forbidden_for_read_only_auditor():
    """REL-081: mutations are SA/PM/RM (broadened from an initial SA-only gate after the SA-only
    version silently hid every mutating control for a PM/RM viewer with no explanation) --
    ReadOnlyAuditor is the only real role left excluded."""
    user_id, token = create_authenticated_user(ROLE_READ_ONLY_AUDITOR)
    try:
        response = client.put(
            f"/api/v1/scheduled-jobs/{_JOB_ID}",
            json={"enabled": False},
            headers=auth_header(token),
        )
        assert response.status_code == 403
    finally:
        cleanup_user(user_id)
    # The forbidden request must not have changed real state.
    with get_session() as session:
        assert (
            session.query(ScheduledJobConfig).filter(ScheduledJobConfig.job_id == _JOB_ID).first()
            is None
        )


@pytest.mark.parametrize("role", [ROLE_PORTFOLIO_MANAGER, ROLE_RISK_MANAGER])
def test_put_allowed_for_pm_and_rm(role):
    user_id, token = create_authenticated_user(role)
    try:
        response = client.put(
            f"/api/v1/scheduled-jobs/{_JOB_ID}",
            json={"enabled": False},
            headers=auth_header(token),
        )
        assert response.status_code == 200
    finally:
        _cleanup_config_row(_JOB_ID)
        cleanup_user(user_id)


def test_put_unknown_job_id_is_a_real_404():
    user_id, token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        response = client.put(
            f"/api/v1/scheduled-jobs/not-a-real-job-{uuid.uuid4().hex[:8]}",
            json={"enabled": False},
            headers=auth_header(token),
        )
        assert response.status_code == 404
    finally:
        cleanup_user(user_id)


def test_put_malformed_cron_is_a_real_400():
    user_id, token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        response = client.put(
            f"/api/v1/scheduled-jobs/{_JOB_ID}",
            json={"cron_expression": "not a cron expression"},
            headers=auth_header(token),
        )
        assert response.status_code == 400
    finally:
        cleanup_user(user_id)


def test_put_empty_body_is_a_real_400():
    user_id, token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        response = client.put(
            f"/api/v1/scheduled-jobs/{_JOB_ID}", json={}, headers=auth_header(token)
        )
        assert response.status_code == 400
    finally:
        cleanup_user(user_id)


def test_put_persists_a_real_config_row_and_a_real_audit_log_row_and_round_trips_on_get():
    from src.models.audit import AuditLog

    user_id, token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        response = client.put(
            f"/api/v1/scheduled-jobs/{_JOB_ID}",
            json={"cron_expression": "0 4 * * *", "enabled": False},
            headers=auth_header(token),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["cron_expression"] == "0 4 * * *"
        assert body["enabled"] is False
        assert body["next_run_time"] is None  # disabled -- honestly nothing scheduled

        detail = client.get(f"/api/v1/scheduled-jobs/{_JOB_ID}", headers=auth_header(token)).json()
        assert detail["cron_expression"] == "0 4 * * *"
        assert detail["enabled"] is False

        with get_session() as session:
            row = (
                session.query(ScheduledJobConfig).filter(ScheduledJobConfig.job_id == _JOB_ID).one()
            )
            assert row.cron_expression == "0 4 * * *"
            assert row.enabled is False
            assert row.updated_by_user_id == user_id

            audit_row = (
                session.query(AuditLog)
                .filter(AuditLog.action == "SCHEDULED_JOB_CONFIG_CHANGED")
                .order_by(AuditLog.id.desc())
                .first()
            )
            assert audit_row is not None
            assert audit_row.after_state["job_id"] == _JOB_ID
    finally:
        # Child rows first -- scheduled_job_config.updated_by_user_id FKs to users.id.
        _cleanup_config_row(_JOB_ID)
        cleanup_user(user_id)


def test_put_reschedules_the_live_scheduler_immediately():
    """The real point of REL-081's `apply_schedule_change`: an edit takes effect on the live
    APScheduler instance without a restart, not just in the DB."""
    live = AsyncIOScheduler(timezone=scheduler_module.IST_TIMEZONE)
    default_cron, _ = scheduler_module.get_effective_schedule(_JOB_ID)
    live.add_job(
        lambda: None,
        CronTrigger.from_crontab(default_cron, timezone=scheduler_module.IST_TIMEZONE),
        id=_JOB_ID,
    )
    scheduler_module._scheduler_instance = live

    user_id, token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        response = client.put(
            f"/api/v1/scheduled-jobs/{_JOB_ID}",
            json={"cron_expression": "0 4 * * *"},
            headers=auth_header(token),
        )
        assert response.status_code == 200
        job = live.get_job(_JOB_ID)
        assert job is not None
        assert "hour='4'" in str(job.trigger)
    finally:
        _cleanup_config_row(_JOB_ID)
        cleanup_user(user_id)


def test_put_pause_and_resume_on_the_live_scheduler():
    live = AsyncIOScheduler(timezone=scheduler_module.IST_TIMEZONE)
    default_cron, _ = scheduler_module.get_effective_schedule(_JOB_ID)
    live.add_job(
        lambda: None,
        CronTrigger.from_crontab(default_cron, timezone=scheduler_module.IST_TIMEZONE),
        id=_JOB_ID,
    )
    scheduler_module._scheduler_instance = live

    user_id, token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        disable = client.put(
            f"/api/v1/scheduled-jobs/{_JOB_ID}", json={"enabled": False}, headers=auth_header(token)
        )
        assert disable.status_code == 200
        assert live.get_job(_JOB_ID).next_run_time is None

        enable = client.put(
            f"/api/v1/scheduled-jobs/{_JOB_ID}", json={"enabled": True}, headers=auth_header(token)
        )
        assert enable.status_code == 200
    finally:
        _cleanup_config_row(_JOB_ID)
        cleanup_user(user_id)


def test_run_now_forbidden_for_read_only_auditor():
    user_id, token = create_authenticated_user(ROLE_READ_ONLY_AUDITOR)
    try:
        response = client.post(
            f"/api/v1/scheduled-jobs/{_JOB_ID}/run-now", headers=auth_header(token)
        )
        assert response.status_code == 403
    finally:
        cleanup_user(user_id)


@pytest.mark.parametrize("role", [ROLE_PORTFOLIO_MANAGER, ROLE_RISK_MANAGER])
def test_run_now_allowed_for_pm_and_rm_on_a_live_scheduler(role):
    live = AsyncIOScheduler(timezone=scheduler_module.IST_TIMEZONE)
    scheduler_module._scheduler_instance = live

    user_id, token = create_authenticated_user(role)
    try:
        response = client.post(
            f"/api/v1/scheduled-jobs/{_JOB_ID}/run-now", headers=auth_header(token)
        )
        assert response.status_code == 202
    finally:
        _cleanup_run_rows(_JOB_ID)
        cleanup_user(user_id)


def test_run_now_unknown_job_id_is_a_real_404():
    user_id, token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        response = client.post(
            f"/api/v1/scheduled-jobs/not-a-real-job-{uuid.uuid4().hex[:8]}/run-now",
            headers=auth_header(token),
        )
        assert response.status_code == 404
    finally:
        cleanup_user(user_id)


def test_run_now_returns_a_real_503_when_no_scheduler_is_running_on_this_process():
    """No test in this suite runs `lifespan`, so this is the real, honest state of this test
    process -- the same real state `app-tls` is in by design."""
    user_id, token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        response = client.post(
            f"/api/v1/scheduled-jobs/{_JOB_ID}/run-now", headers=auth_header(token)
        )
        assert response.status_code == 503
    finally:
        cleanup_user(user_id)


def test_run_now_dispatches_on_a_live_scheduler_and_creates_a_real_running_row():
    live = AsyncIOScheduler(timezone=scheduler_module.IST_TIMEZONE)
    scheduler_module._scheduler_instance = live

    user_id, token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        response = client.post(
            f"/api/v1/scheduled-jobs/{_JOB_ID}/run-now", headers=auth_header(token)
        )
        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "Running"
        run_id = uuid.UUID(body["job_run_id"])

        with get_session() as session:
            row = session.get(ScheduledJobRun, run_id)
            assert row is not None
            assert row.job_id == _JOB_ID
            assert row.trigger_source == "manual"
            assert row.status == "Running"
            assert row.triggered_by_user_id == user_id

        # The manual dispatch was actually queued on the live instance, not silently dropped.
        assert any(j.id.startswith(f"{_JOB_ID}-manual-") for j in live.get_jobs())
    finally:
        _cleanup_run_rows(_JOB_ID)
        cleanup_user(user_id)
        _cleanup_run_rows(_JOB_ID)
