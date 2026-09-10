"""MANDATORY concurrency test (spec T041, brief section 78, SC-001/SC-002).

Four independent concurrency-safe tasks must run with overlapping wall-clock windows; dependent
tasks must not start before their prerequisite completes; no task may run with a required input
absent.
"""

import pytest
from sqlalchemy import select

from src.core.config import get_settings
from src.core.db import get_session
from src.models.orchestration import Task
from src.orchestration import task_engine
from src.orchestration.enums import TaskStatus
from tests.orchestration_helpers import cleanup_run, seed_run_with_tasks


@pytest.fixture(autouse=True)
def _slow_placeholder(monkeypatch: pytest.MonkeyPatch):
    # Each placeholder task takes ~0.15s so parallel windows deterministically overlap.
    monkeypatch.setenv("ORG_PLACEHOLDER_TASK_DELAY_SECONDS", "0.15")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_independent_tasks_overlap_and_dependents_wait():
    run_id, _ = seed_run_with_tasks(
        [
            {"key": "market", "capability": "market_analysis", "assigned_agent": "market_analyst"},
            {"key": "news", "capability": "news_ingestion", "assigned_agent": "news_agent"},
            {
                "key": "portfolio",
                "capability": "portfolio_read",
                "assigned_agent": "portfolio_manager_agent",
            },
            {
                "key": "fresh",
                "capability": "data_freshness",
                "assigned_agent": "data_ingestion_agent",
            },
            {
                "key": "sentiment",
                "capability": "sentiment_analysis",
                "assigned_agent": "sentiment_agent",
                "depends_on": ["news"],
            },
            {
                "key": "synth",
                "capability": "synthesize",
                "assigned_agent": "ceo_agent",
                "depends_on": ["market", "news", "portfolio", "fresh", "sentiment"],
            },
        ]
    )
    try:
        task_engine.run_scheduler_loop(run_id)

        with get_session() as session:
            tasks = {
                t.capability: t
                for t in session.scalars(select(Task).where(Task.run_id == run_id)).all()
            }

        independent = ["market_analysis", "news_ingestion", "portfolio_read", "data_freshness"]
        for cap in independent:
            assert tasks[cap].status == TaskStatus.COMPLETED.value, f"{cap} did not complete"
            assert tasks[cap].started_at is not None and tasks[cap].completed_at is not None

        # SC-001: at least three of the four independent windows overlap a sibling.
        overlapping = [c for c in independent if tasks[c].ran_concurrently]
        assert len(overlapping) >= 3, f"expected parallel execution, got {overlapping}"

        # SC-002: dependents start at/after their last prerequisite completes.
        assert tasks["sentiment_analysis"].started_at >= tasks["news_ingestion"].completed_at
        latest_dep = max(tasks[c].completed_at for c in independent + ["sentiment_analysis"])
        assert tasks["synthesize"].started_at >= latest_dep

        # Independent tasks did not wait on anything.
        for cap in independent:
            assert tasks[cap].dependency_wait_seconds == 0
        # No task ran with a missing required input.
        assert len(tasks["synthesize"].received_inputs) == 5
        assert tasks["synthesize"].status == TaskStatus.COMPLETED.value
    finally:
        cleanup_run(run_id)
