"""Blocked-dependency test (spec T043, FR-017).

An upstream task that permanently fails must leave its dependent ``blocked`` with a clear
reason -- never falsely ``completed``.
"""

from unittest.mock import patch

from sqlalchemy import select

from src.core.db import get_session
from src.models.orchestration import Task
from src.orchestration import agent_invoker, task_engine
from src.orchestration.enums import TaskStatus
from tests.orchestration_helpers import cleanup_run, seed_run_with_tasks

_real_dispatch = agent_invoker.dispatch


def test_upstream_failure_blocks_the_dependent_task():
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
            raise RuntimeError("simulated agent failure")
        return _real_dispatch(session, task)

    try:
        with patch("src.orchestration.agent_invoker.dispatch", side_effect=_dispatch):
            task_engine.run_scheduler_loop(run_id)

        with get_session() as session:
            tasks = {
                t.capability: t
                for t in session.scalars(select(Task).where(Task.run_id == run_id)).all()
            }
            a, b = tasks["market_analysis"], tasks["synthesize"]
            assert a.status == TaskStatus.FAILED.value
            assert a.retry_count == a.max_retries
            assert b.status == TaskStatus.BLOCKED.value
            assert b.blocked_reason and "failed" in b.blocked_reason
            assert b.status != TaskStatus.COMPLETED.value

            from src.models.orchestration import OrganizationRun

            run = session.get(OrganizationRun, run_id)
            assert run is not None and run.status == "failed"
    finally:
        cleanup_run(run_id)
