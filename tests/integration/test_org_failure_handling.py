"""(Failure -- MANDATORY) Integration test (spec T106, brief §82, quickstart Scenario 9,
SC-017): a forced agent failure exhausts the bounded retry ladder, records a real CEO/org
failure event with an `AuditLog` entry, notifies a human (T106's own ops-alert addition to
`task_engine._handle_task_failure`), and never leaves a dependent falsely `completed` -- the
dependency-blocking half of this is already covered end-to-end by
`test_org_blocked_dependency.py` (T043); this test's distinct job is the audit trail + human
notification + truthful run-level state.
"""

from unittest.mock import patch

from sqlalchemy import select

from src.core.db import get_session
from src.models.audit import AuditLog
from src.models.orchestration import OrganizationRun, Task
from src.orchestration import agent_invoker, task_engine
from src.orchestration.enums import RunStatus, TaskStatus
from tests.orchestration_helpers import cleanup_run, seed_run_with_tasks

_real_dispatch = agent_invoker.dispatch


def test_a_repeatedly_failing_task_notifies_a_human_and_leaves_a_real_audit_trail():
    run_id, keys = seed_run_with_tasks(
        [
            {"key": "a", "capability": "market_analysis", "assigned_agent": "market_analyst"},
            {
                "key": "b",
                "capability": "synthesize",
                "assigned_agent": "ceo_agent",
                "depends_on": ["a"],
            },
        ]
    )
    failing_id = keys["a"]

    def _dispatch(session, task):  # type: ignore[no-untyped-def]
        if task.id == failing_id:
            raise RuntimeError("simulated repeated agent failure")
        return _real_dispatch(session, task)

    try:
        with (
            patch("src.orchestration.agent_invoker.dispatch", side_effect=_dispatch),
            patch("src.core.ops_alerts.send_ops_alert") as mock_alert,
        ):
            task_engine.run_scheduler_loop(run_id)

        with get_session() as session:
            tasks = {
                t.capability: t
                for t in session.scalars(select(Task).where(Task.run_id == run_id)).all()
            }
            failed_task, dependent = tasks["market_analysis"], tasks["synthesize"]

            # Task failed after exhausting its retry budget, never falsely completed.
            assert failed_task.status == TaskStatus.FAILED.value
            assert failed_task.retry_count == failed_task.max_retries
            assert dependent.status == TaskStatus.BLOCKED.value
            assert dependent.status != TaskStatus.COMPLETED.value

            # A real AuditLog entry exists for the task-level failure event.
            audit_rows = session.scalars(
                select(AuditLog).where(
                    AuditLog.entity_id == failed_task.id,
                    AuditLog.action == "ORG_EVENT_TASK_FAILED",
                )
            ).all()
            assert len(audit_rows) == 1

            # A real, distinct CEO/org-level failure event exists too (the run itself, not just
            # the one task) -- truthful console state: the run genuinely did not succeed.
            run = session.get(OrganizationRun, run_id)
            assert run is not None
            assert run.status == RunStatus.FAILED.value
            run_failure_audit = session.scalars(
                select(AuditLog).where(
                    AuditLog.entity_id == run_id,
                    AuditLog.action == "ORG_EVENT_ORGANIZATION_RUN_FAILED",
                )
            ).all()
            assert len(run_failure_audit) == 1

        # A human was notified once the retry budget was exhausted (best-effort ops alert --
        # patched here rather than asserting on a real Telegram/Discord/Slack send, since this
        # dev environment may or may not have those webhooks configured).
        assert mock_alert.await_count >= 1
        alerted_text = " ".join(str(call.args[0]) for call in mock_alert.await_args_list)
        assert "market_analysis" in alerted_text
    finally:
        cleanup_run(run_id)


def test_a_failing_task_is_observably_retrying_not_silently_ready_again():
    """spec 002 US7: between a failure and the next dispatch claim, the task's real status is
    `RETRYING` -- previously it went straight back to `READY`, indistinguishable from a task
    that never failed at all."""
    run_id, keys = seed_run_with_tasks(
        [{"key": "a", "capability": "market_analysis", "assigned_agent": "market_analyst"}]
    )
    try:
        task_engine._handle_task_failure(run_id, keys["a"], RuntimeError("first attempt failed"))
        with get_session() as session:
            task = session.get(Task, keys["a"])
            assert task is not None
            assert task.status == TaskStatus.RETRYING.value
            assert task.retry_count == 1
    finally:
        cleanup_run(run_id)


def test_a_task_that_fails_once_then_succeeds_completes_with_retry_count_one():
    """spec 002 US7 (closes the recovery-path test gap the original audit flagged as missing):
    a task that fails on its first attempt and succeeds on its second reaches `COMPLETED` with
    `retry_count == 1` -- the retry mechanism genuinely recovers, not just genuinely exhausts."""
    run_id, keys = seed_run_with_tasks(
        [{"key": "a", "capability": "market_analysis", "assigned_agent": "market_analyst"}]
    )
    failing_id = keys["a"]
    attempts = {"count": 0}

    def _dispatch(session, task):  # type: ignore[no-untyped-def]
        if task.id == failing_id and attempts["count"] == 0:
            attempts["count"] += 1
            raise RuntimeError("transient failure, recovers on retry")
        return _real_dispatch(session, task)

    try:
        with patch("src.orchestration.agent_invoker.dispatch", side_effect=_dispatch):
            task_engine.run_scheduler_loop(run_id)

        with get_session() as session:
            task = session.get(Task, failing_id)
            assert task is not None
            assert task.status == TaskStatus.COMPLETED.value
            assert task.retry_count == 1
    finally:
        cleanup_run(run_id)


def test_a_permanently_escalated_task_is_distinct_from_failed():
    """spec 002 US7: a task with no available agent for its capability escalates to a human
    (`ESCALATE_HUMAN` decision) with its own `ESCALATED` status -- distinct from `FAILED`, which
    means "retries exhausted," not "a human needs to act."""
    from src.orchestration import agent_invoker as agent_invoker_module

    run_id, keys = seed_run_with_tasks(
        [{"key": "a", "capability": "market_analysis", "assigned_agent": "market_analyst"}]
    )
    try:
        with patch(
            "src.orchestration.agent_invoker.dispatch",
            side_effect=agent_invoker_module.AgentUnavailable("no agent declares this capability"),
        ):
            task_engine.run_scheduler_loop(run_id)

        with get_session() as session:
            task = session.get(Task, keys["a"])
            assert task is not None
            assert task.status == TaskStatus.ESCALATED.value
            assert task.status != TaskStatus.FAILED.value

            run = session.get(OrganizationRun, run_id)
            assert run is not None
            assert run.status == RunStatus.FAILED.value
            assert run.result_summary is not None
            assert run.result_summary.get("escalated_tasks") == 1
    finally:
        cleanup_run(run_id)
