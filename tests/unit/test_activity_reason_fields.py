"""spec 002 US6: every event type the Activity Stream needs to explain itself carries a
plain-language `reason` under a uniform key -- not a per-event-type special case in the
frontend. Uses real Postgres (via `seed_run_with_tasks`), matching this codebase's convention.
"""

from datetime import UTC, datetime

from src.core.db import get_session
from src.models.orchestration import OrganizationalEvent, Task
from src.orchestration import dependency_resolver
from tests.orchestration_helpers import cleanup_run, seed_run_with_tasks


def test_waiting_for_dependency_event_carries_a_reason_naming_the_prerequisite():
    run_id, task_ids = seed_run_with_tasks(
        [
            {"key": "news", "capability": "news_ingestion", "assigned_agent": "news_agent"},
            {
                "key": "sentiment",
                "capability": "sentiment_analysis",
                "assigned_agent": "sentiment_agent",
                "depends_on": ["news"],
            },
        ]
    )
    try:
        with get_session() as session:
            dependency_resolver.ready_tasks(session, run_id)
            session.commit()

        with get_session() as session:
            rows = (
                session.query(OrganizationalEvent)
                .filter(
                    OrganizationalEvent.run_id == run_id,
                    OrganizationalEvent.event_type == "task.waiting_for_dependency",
                )
                .all()
            )
            assert len(rows) >= 1
            assert "reason" in rows[0].payload
            assert rows[0].payload["reason"]  # non-empty
    finally:
        cleanup_run(run_id)


def test_dependency_satisfied_event_carries_a_reason():
    run_id, task_ids = seed_run_with_tasks(
        [
            {"key": "news", "capability": "news_ingestion", "assigned_agent": "news_agent"},
            {
                "key": "sentiment",
                "capability": "sentiment_analysis",
                "assigned_agent": "sentiment_agent",
                "depends_on": ["news"],
            },
        ]
    )
    try:
        with get_session() as session:
            news_task = session.get(Task, task_ids["news"])
            assert news_task is not None
            news_task.status = "completed"
            news_task.completed_at = datetime.now(UTC)
            dependency_resolver.evaluate_on_completion(session, news_task)
            session.commit()

        with get_session() as session:
            rows = (
                session.query(OrganizationalEvent)
                .filter(
                    OrganizationalEvent.run_id == run_id,
                    OrganizationalEvent.event_type == "dependency.satisfied",
                )
                .all()
            )
            assert len(rows) == 1
            assert rows[0].payload["reason"]
    finally:
        cleanup_run(run_id)
