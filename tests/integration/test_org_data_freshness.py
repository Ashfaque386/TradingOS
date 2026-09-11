"""Data-freshness awareness integration test (spec T090, quickstart Scenario 7, SC-006, BUG-A).

A stale/unavailable required dataset blocks only the task(s) that need it -- independent tasks
still run, a real `task.blocked` event names the dataset, and nothing synthetic is fabricated in
its place. A subsequent real, checksum-passing ingestion makes the dataset fresh again, so a
freshly-dispatched task with the same requirement is no longer blocked by it.
"""

from sqlalchemy import select

from src.core.db import get_session
from src.models.dataset_freshness import DatasetFreshnessRecord
from src.models.orchestration import OrganizationalEvent, ResultArtefact, Task
from src.orchestration import freshness, task_engine
from src.orchestration.enums import TaskStatus
from tests.orchestration_helpers import cleanup_run, seed_run_with_tasks

_DATASET = "ohlcv_daily"


def _reset_dataset() -> None:
    with get_session() as session:
        session.query(DatasetFreshnessRecord).filter(
            DatasetFreshnessRecord.dataset_name == _DATASET
        ).delete()
        session.commit()


def test_stale_dataset_blocks_only_the_dependent_task():
    _reset_dataset()
    run_id, _keys = seed_run_with_tasks(
        [
            {
                "key": "indep",
                "capability": "sentiment_analysis",
                "assigned_agent": "sentiment_agent",
            },
            {
                "key": "needs_data",
                "capability": "market_analysis",
                "assigned_agent": "market_analyst",
                "required_datasets": [_DATASET],
            },
        ]
    )
    try:
        # No ingestion has ever run for this dataset -> "unavailable", not fresh.
        with get_session() as session:
            assert freshness.is_fresh(session, _DATASET) is False

        task_engine.run_scheduler_loop(run_id)

        with get_session() as session:
            tasks = {
                t.capability: t
                for t in session.scalars(select(Task).where(Task.run_id == run_id)).all()
            }
            indep = tasks["sentiment_analysis"]
            needs_data = tasks["market_analysis"]
            assert indep.status == TaskStatus.COMPLETED.value
            assert needs_data.status == TaskStatus.BLOCKED.value
            assert needs_data.blocked_reason == f"data stale: {_DATASET}"
            assert needs_data.result_artefact_id is None

            # No synthetic artefact was fabricated for the blocked task.
            artefacts = session.scalars(
                select(ResultArtefact).where(ResultArtefact.task_id == needs_data.id)
            ).all()
            assert artefacts == []

            events = session.scalars(
                select(OrganizationalEvent).where(OrganizationalEvent.run_id == run_id)
            ).all()
            blocked_events = [e for e in events if e.event_type == "task.blocked"]
            assert any(e.payload.get("dataset") == _DATASET for e in blocked_events)
    finally:
        cleanup_run(run_id)
        _reset_dataset()


def test_a_real_checksum_passing_ingestion_unblocks_new_dispatches():
    _reset_dataset()
    run_id, keys = seed_run_with_tasks(
        [
            {
                "key": "needs_data",
                "capability": "market_analysis",
                "assigned_agent": "market_analyst",
                "required_datasets": [_DATASET],
            }
        ]
    )
    try:
        with get_session() as session:
            assert freshness.is_fresh(session, _DATASET) is False

        # A real, checksum-passing ingestion (not a synthetic backfill) makes it fresh again.
        with get_session() as session:
            freshness.record_ingestion_result(
                session, _DATASET, success=True, checksum_ok=True, has_data=True
            )
            session.commit()
        with get_session() as session:
            assert freshness.is_fresh(session, _DATASET) is True

        task_engine.run_scheduler_loop(run_id)

        with get_session() as session:
            task = session.get(Task, keys["needs_data"])
            assert task is not None
            assert task.status == TaskStatus.COMPLETED.value
            assert task.blocked_reason is None
    finally:
        cleanup_run(run_id)
        _reset_dataset()
