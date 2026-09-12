"""spec 002 US3: `list_handoffs` derives a first-class handoff row per (producer task ->
consumer task, artefact) triple from existing `ResultArtefact.consumed_by_task_ids` +
`Task.received_inputs`/`required_inputs` -- no new table, no new write path. Uses real Postgres
(via `seed_run_with_tasks`), matching this codebase's convention for orchestration-layer tests
that need real DB-backed fixtures even when filed under `tests/unit/`.
"""

from datetime import UTC, datetime

from src.core.db import get_session
from src.models.orchestration import ResultArtefact, Task
from src.orchestration.handoffs import list_handoffs, list_handoffs_for_agent
from tests.orchestration_helpers import cleanup_run, seed_run_with_tasks


def test_list_handoffs_produces_one_row_per_producer_consumer_artefact_pair():
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
            sentiment_task = session.get(Task, task_ids["sentiment"])
            assert sentiment_task is not None
            sentiment_task.required_inputs = ["NewsDigest", "MarketContext"]

            artefact = ResultArtefact(
                run_id=run_id,
                task_id=task_ids["news"],
                artefact_type="NewsDigest",
                version=1,
                payload={"headlines": []},
                provenance={"agent": "news_agent"},
                disposition="consumed",
                consumed_by_task_ids=[str(task_ids["sentiment"])],
                created_at=datetime.now(UTC),
            )
            session.add(artefact)
            session.flush()
            artefact_id = artefact.id

            # The consumer only actually received NewsDigest -- MarketContext is still missing,
            # so requested_but_missing must surface it.
            sentiment_task.received_inputs = [
                {"artefact_id": str(artefact_id), "type": "NewsDigest"}
            ]
            session.commit()

        with get_session() as session:
            rows = list_handoffs(session, run_id)
            assert len(rows) == 1
            row = rows[0]
            assert row["from_task_id"] == str(task_ids["news"])
            assert row["from_agent"] == "news_agent"
            assert row["to_task_id"] == str(task_ids["sentiment"])
            assert row["to_agent"] == "sentiment_agent"
            assert row["artefact_id"] == str(artefact_id)
            assert row["artefact_type"] == "NewsDigest"
            assert row["requested_but_missing"] == ["MarketContext"]

            by_agent = list_handoffs_for_agent(session, run_id, "sentiment_agent")
            assert len(by_agent["inbound"]) == 1
            assert by_agent["inbound"][0]["artefact_id"] == str(artefact_id)
            assert by_agent["outbound"] == []

            by_agent_news = list_handoffs_for_agent(session, run_id, "news_agent")
            assert by_agent_news["outbound"] == rows
            assert by_agent_news["inbound"] == []
    finally:
        cleanup_run(run_id)


def test_list_handoffs_is_empty_for_a_run_with_no_artefact_consumption():
    run_id, _task_ids = seed_run_with_tasks(
        [{"key": "solo", "capability": "market_analysis", "assigned_agent": "market_analyst"}]
    )
    try:
        with get_session() as session:
            assert list_handoffs(session, run_id) == []
    finally:
        cleanup_run(run_id)


def test_list_handoffs_no_duplicates_when_one_artefact_has_multiple_consumers():
    run_id, task_ids = seed_run_with_tasks(
        [
            {"key": "market", "capability": "market_analysis", "assigned_agent": "market_analyst"},
            {
                "key": "strategy",
                "capability": "strategy_research",
                "assigned_agent": "strategy_generator",
                "depends_on": ["market"],
            },
            {
                "key": "risk",
                "capability": "risk_assessment",
                "assigned_agent": "risk_manager",
                "depends_on": ["market"],
            },
        ]
    )
    try:
        with get_session() as session:
            artefact = ResultArtefact(
                run_id=run_id,
                task_id=task_ids["market"],
                artefact_type="MarketContext",
                version=1,
                payload={},
                provenance={"agent": "market_analyst"},
                disposition="consumed",
                consumed_by_task_ids=[str(task_ids["strategy"]), str(task_ids["risk"])],
                created_at=datetime.now(UTC),
            )
            session.add(artefact)
            session.commit()

        with get_session() as session:
            rows = list_handoffs(session, run_id)
            assert len(rows) == 2, "one row per distinct consumer, no duplicates and none omitted"
            consumer_ids = {r["to_task_id"] for r in rows}
            assert consumer_ids == {str(task_ids["strategy"]), str(task_ids["risk"])}
    finally:
        cleanup_run(run_id)
