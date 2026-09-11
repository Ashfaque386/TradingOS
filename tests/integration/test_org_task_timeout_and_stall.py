"""Per-task timeout + stalled-run sweep (spec T108, research R20).

- a task whose handler outlives its own `timeout_seconds` is declared `failed` (never left
  `running` forever), its `failure_reason` names the timeout, and its dependent is `blocked`,
  never falsely `completed`;
- `task_engine.check_stalled_runs()` flags a `waiting` run `stalled` once
  `ORG_RUN_STALL_SECONDS` has passed with no progress;
- a `waiting` run with a pending approval is never flagged `stalled` -- it's legitimately
  waiting on a human (FR-057).
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from src.core.db import get_session
from src.models.orchestration import OrganizationRun, Task
from src.orchestration import task_engine
from src.orchestration.enums import RunStatus, TaskStatus
from tests.orchestration_helpers import cleanup_run, seed_run_with_tasks


def test_a_task_that_outlives_its_timeout_is_failed_not_left_running(monkeypatch):
    # "data_freshness" isn't in agent_invoker.CAPABILITY_HANDLERS, so it goes through
    # `_placeholder_handler`, which honours ORG_PLACEHOLDER_TASK_DELAY_SECONDS -- a real,
    # existing hook for making a task's handler take a deterministic amount of time, no need to
    # monkeypatch dispatch internals.
    monkeypatch.setenv("ORG_PLACEHOLDER_TASK_DELAY_SECONDS", "2")
    from src.core.config import get_settings

    get_settings.cache_clear()  # type: ignore[attr-defined]
    try:
        run_id, keys = seed_run_with_tasks(
            [
                {
                    "key": "slow",
                    "capability": "data_freshness",
                    "assigned_agent": "data_ingestion_agent",
                    "timeout_seconds": 1,
                },
                {
                    "key": "dependent",
                    "capability": "synthesize",
                    "assigned_agent": "ceo_agent",
                    "depends_on": ["slow"],
                },
            ]
        )
        try:
            task_engine.run_scheduler_loop(run_id)

            with get_session() as session:
                slow = session.get(Task, keys["slow"])
                dependent = session.get(Task, keys["dependent"])
                assert slow is not None and dependent is not None
                assert slow.status == TaskStatus.FAILED.value
                assert "timed out" in (slow.failure_reason or "")
                assert dependent.status == TaskStatus.BLOCKED.value
                assert dependent.result_artefact_id is None
        finally:
            cleanup_run(run_id)
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]


def test_check_stalled_runs_flags_a_waiting_run_with_no_progress():
    run_id, _ = seed_run_with_tasks(
        [{"key": "a", "capability": "market_analysis", "assigned_agent": "market_analyst"}]
    )
    try:
        stale = datetime.now(UTC) - timedelta(hours=1)
        with get_session() as session:
            run = session.get(OrganizationRun, run_id)
            assert run is not None
            run.status = RunStatus.WAITING.value
            run.updated_at = stale
            session.commit()

        with patch("src.orchestration.task_engine.get_settings") as mock_settings:
            mock_settings.return_value.org_run_stall_seconds = 60
            flagged = task_engine.check_stalled_runs()

        assert flagged >= 1
        with get_session() as session:
            run = session.get(OrganizationRun, run_id)
            assert run is not None
            assert run.status == RunStatus.STALLED.value
    finally:
        cleanup_run(run_id)


def test_check_stalled_runs_never_flags_a_run_with_a_pending_approval():
    run_id, _ = seed_run_with_tasks(
        [{"key": "a", "capability": "market_analysis", "assigned_agent": "market_analyst"}]
    )
    try:
        stale = datetime.now(UTC) - timedelta(hours=1)
        with get_session() as session:
            run = session.get(OrganizationRun, run_id)
            assert run is not None
            run.status = RunStatus.WAITING.value
            run.updated_at = stale
            session.commit()

        with (
            patch("src.orchestration.task_engine.get_settings") as mock_settings,
            patch(
                "src.orchestration.task_engine._has_pending_approval",
                return_value=True,
            ),
        ):
            mock_settings.return_value.org_run_stall_seconds = 60
            task_engine.check_stalled_runs()

        with get_session() as session:
            run = session.get(OrganizationRun, run_id)
            assert run is not None
            assert run.status == RunStatus.WAITING.value  # unchanged -- not stalled
    finally:
        cleanup_run(run_id)
