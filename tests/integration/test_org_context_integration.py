"""News/sentiment/portfolio -> research context integration test (spec T060, quickstart
Scenario 4, SC-004/005, FR-042/043/044).

- the `context_assembly` task produces a `ResearchContext` whose provenance references *this
  run's* `NewsDigest` + `SentimentReport` artefacts;
- the downstream strategy task's `received_inputs` include that `ResearchContext`;
- no artefact is left undispositioned when the run completes (SC-004);
- a source that is legitimately absent -> `coverage="reduced"` + the missing input listed;
- a `PortfolioRiskReport` artefact id is folded into a CEO decision's supporting inputs (FR-043).
"""

from datetime import UTC, datetime

from qdrant_client import QdrantClient
from sqlalchemy import select

from src.core.config import get_settings
from src.core.db import get_session
from src.memory.news_memory import ingest_news_sentiment
from src.models.orchestration import OrganizationRun, ResultArtefact, Task
from src.orchestration import decisions, freshness, task_engine
from src.orchestration.enums import DecisionType, TaskStatus
from tests.orchestration_helpers import cleanup_run, seed_run_with_tasks

_FULL_PLAN = [
    {
        "key": "news",
        "capability": "news_ingestion",
        "assigned_agent": "news_agent",
        "expected_output": "NewsDigest",
    },
    {
        "key": "sentiment",
        "capability": "sentiment_analysis",
        "assigned_agent": "sentiment_agent",
        "expected_output": "SentimentReport",
        "depends_on": ["news"],
    },
    {
        "key": "market",
        "capability": "market_analysis",
        "assigned_agent": "market_analyst",
        "expected_output": "MarketContext",
    },
    {
        "key": "portfolio",
        "capability": "portfolio_read",
        "assigned_agent": "portfolio_manager_agent",
        "expected_output": "PortfolioRiskReport",
    },
    {
        "key": "fresh",
        "capability": "data_freshness",
        "assigned_agent": "data_ingestion_agent",
        "expected_output": "AdHocAnalysis",
    },
    {
        "key": "ctx",
        "capability": "context_assembly",
        "assigned_agent": "ceo_agent",
        "expected_output": "ResearchContext",
        "depends_on": ["news", "sentiment", "market", "portfolio", "fresh"],
    },
    {
        "key": "strat",
        "capability": "strategy_generation",
        "assigned_agent": "strategy_generator",
        "expected_output": "AdHocAnalysis",
        "depends_on": ["ctx"],
    },
]


def _artefacts(run_id):
    with get_session() as session:
        return list(
            session.scalars(select(ResultArtefact).where(ResultArtefact.run_id == run_id)).all()
        )


def test_research_context_is_assembled_and_threaded_into_the_strategy_task():
    # T113: `news_ingestion`/`sentiment_analysis` are real handlers now (real Qdrant reads of
    # `news_sentiment` + the real "news" freshness record) -- seed both so this "everything
    # available" happy path genuinely earns `coverage="full"` rather than a hardcoded one.
    with get_session() as session:
        freshness.record_ingestion_result(
            session, "news", success=True, checksum_ok=True, has_data=True
        )
        session.commit()
    point_id = ingest_news_sentiment(
        title="Nifty IT index rallies on strong Q1 earnings",
        summary="IT majors reported better-than-expected quarterly results.",
        source="test-seed",
        url="https://example.invalid/article",
        published_at=datetime.now(UTC),
        sentiment="Bullish",
        confidence=0.85,
        symbols_mentioned=["INFY"],
    )
    run_id, keys = seed_run_with_tasks(_FULL_PLAN)
    try:
        task_engine.run_scheduler_loop(run_id)

        arts = _artefacts(run_id)
        by_type = {a.artefact_type: a for a in arts}
        assert "ResearchContext" in by_type, [a.artefact_type for a in arts]
        rc = by_type["ResearchContext"]

        news_id = str(by_type["NewsDigest"].id)
        sent_id = str(by_type["SentimentReport"].id)
        assert news_id in rc.provenance["inputs"]
        assert sent_id in rc.provenance["inputs"]
        assert rc.payload["coverage"] == "full"
        assert rc.payload["missing_inputs"] == []

        # SC-004: nothing orphaned.
        assert all(a.disposition is not None for a in arts)

        with get_session() as session:
            strat = session.get(Task, keys["strat"])
            assert strat is not None and strat.status == TaskStatus.COMPLETED.value
            types = {ri.get("type") for ri in strat.received_inputs}
            assert "ResearchContext" in types

        # FR-043 / T056: a portfolio artefact id is folded into a CEO decision's inputs.
        portfolio_id = str(by_type["PortfolioRiskReport"].id)
        with get_session() as session:
            run = session.get(OrganizationRun, run_id)
            decision = decisions.record_decision(
                session,
                run,
                decision_type=DecisionType.PROCEED,
                summary="Proceed to strategy generation.",
                reason="Context assembled; no blocking conflict.",
            )
            session.commit()
            assert portfolio_id in decision.supporting_input_artefact_ids
    finally:
        cleanup_run(run_id)
        QdrantClient(url=get_settings().qdrant_url).delete(
            collection_name="news_sentiment", points_selector=[point_id]
        )


def test_missing_news_marks_the_context_reduced_with_the_gap_named():
    plan = [t for t in _FULL_PLAN if t["key"] != "news"]
    plan = [{**t, "depends_on": [d for d in t.get("depends_on", []) if d != "news"]} for t in plan]
    run_id, _ = seed_run_with_tasks(plan)
    try:
        task_engine.run_scheduler_loop(run_id)

        by_type = {a.artefact_type: a for a in _artefacts(run_id)}
        assert "ResearchContext" in by_type
        rc = by_type["ResearchContext"]
        assert rc.payload["coverage"] == "reduced"
        assert "NewsDigest" in rc.payload["missing_inputs"]
        assert "NewsDigest" not in by_type  # nothing fabricated in its place
    finally:
        cleanup_run(run_id)
