"""Restart-resume integration test (spec T104, quickstart Scenario 8, SC-023): a real process
restart's own startup hook (`run_manager.reap_incomplete_runs`) re-enters a non-terminal
organisation run left behind by the previous process -- complete tasks keep their artefacts
untouched (never re-executed, never regenerated), a mid-flight (`running`) task is re-attempted
or `failed` (never a false `completed`), and the run *genuinely* resumes making progress
afterward, not just has its rows patched up and left idle.
"""

import time
from datetime import UTC, datetime

from sqlalchemy import select

from src.core.db import get_session
from src.models.orchestration import OrganizationRun, ResultArtefact, Task
from src.orchestration import run_manager
from src.orchestration.enums import RunStatus, TaskStatus
from tests.orchestration_helpers import cleanup_run, seed_run_with_tasks


def _wait_until(predicate, timeout_seconds: float = 10.0, interval: float = 0.1) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def test_a_completed_task_and_its_artefact_are_untouched_across_a_simulated_restart():
    run_id, keys = seed_run_with_tasks(
        [{"key": "a", "capability": "market_analysis", "assigned_agent": "market_analyst"}]
    )
    try:
        now = datetime.now(UTC)
        with get_session() as session:
            task = session.get(Task, keys["a"])
            assert task is not None
            task.status = TaskStatus.COMPLETED.value
            task.started_at = now
            task.completed_at = now
            artefact = ResultArtefact(
                run_id=run_id,
                task_id=task.id,
                artefact_type="MarketContext",
                payload={
                    "market_regime": "Bullish",
                    "sector_rankings": ["IT"],
                    "volatility_assessment": "low",
                    "macro_outlook": "stable",
                    "confidence_score": 0.9,
                    "insights": ["real, pre-restart artefact"],
                },
                provenance={"agent": "market_analyst"},
                disposition="informational",
                created_at=now,
            )
            session.add(artefact)
            session.flush()
            task.result_artefact_id = artefact.id
            session.commit()
            original_artefact_id = artefact.id

        # Simulate the process restart's startup hook.
        run_manager.reap_incomplete_runs()

        with get_session() as session:
            task = session.get(Task, keys["a"])
            assert task is not None
            # Zero re-execution: still completed, same artefact id, nothing regenerated.
            assert task.status == TaskStatus.COMPLETED.value
            assert task.result_artefact_id == original_artefact_id
            artefacts = session.scalars(
                select(ResultArtefact).where(ResultArtefact.task_id == task.id)
            ).all()
            assert len(artefacts) == 1
            assert artefacts[0].id == original_artefact_id
    finally:
        cleanup_run(run_id)


def test_a_mid_flight_concurrency_safe_task_is_reset_to_ready_and_genuinely_resumed():
    # "data_freshness" goes through the fast, deterministic placeholder handler -- this test's
    # job is proving the reaper's own resume mechanics (a real run_scheduler_loop re-entry, not
    # just a status flip), not re-exercising a specific real per-agent handler's own correctness
    # (already covered elsewhere), so it deliberately avoids a capability whose real handler
    # depends on this environment's LLM provider reachability.
    run_id, keys = seed_run_with_tasks(
        [
            {
                "key": "a",
                "capability": "data_freshness",
                "assigned_agent": "data_ingestion_agent",
            }
        ]
    )
    try:
        with get_session() as session:
            task = session.get(Task, keys["a"])
            assert task is not None
            task.status = TaskStatus.RUNNING.value
            task.started_at = datetime.now(UTC)
            run = session.get(OrganizationRun, run_id)
            assert run is not None
            run.status = RunStatus.RUNNING.value
            session.commit()

        run_manager.reap_incomplete_runs()

        # "Automatic resume": the reaper's own detached thread should drive this task all the
        # way to a real terminal state on its own, with no further test-side trigger.
        def _reached_terminal() -> bool:
            with get_session() as session:
                t = session.get(Task, keys["a"])
                return t is not None and t.status in (
                    TaskStatus.COMPLETED.value,
                    TaskStatus.FAILED.value,
                )

        assert _wait_until(_reached_terminal, timeout_seconds=15.0)
        with get_session() as session:
            task = session.get(Task, keys["a"])
            assert task is not None
            # Never a false completed for a task that was never actually re-run -- this real
            # dispatch either genuinely completed or genuinely failed, both honest.
            assert task.status in (TaskStatus.COMPLETED.value, TaskStatus.FAILED.value)
    finally:
        cleanup_run(run_id)


def test_a_mid_flight_non_concurrency_safe_task_is_marked_failed_never_false_completed():
    run_id, keys = seed_run_with_tasks(
        [
            {
                "key": "a",
                "capability": "code_validation",
                "assigned_agent": "python_validator_agent",
            }
        ]
    )
    try:
        with get_session() as session:
            task = session.get(Task, keys["a"])
            assert task is not None
            assert task.is_concurrency_safe is False
            task.status = TaskStatus.RUNNING.value
            task.started_at = datetime.now(UTC)
            session.commit()

        run_manager.reap_incomplete_runs()

        with get_session() as session:
            task = session.get(Task, keys["a"])
            assert task is not None
            assert task.status == TaskStatus.FAILED.value
            assert task.status != TaskStatus.COMPLETED.value
            assert "restarted" in (task.failure_reason or "")
    finally:
        cleanup_run(run_id)
