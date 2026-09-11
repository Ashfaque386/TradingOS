"""strategy_research handler (spec T113b): the composite capability that runs the real
build_graph() sub-graph as a task-engine dispatch.

- the assembled ResearchContext (if any) is threaded into the graph's initial state;
- the result artefact is whichever real typed output the graph's last node actually produced,
  read back via graph_thread_id -- never a fabricated DeploymentRecommendation when the run
  stopped earlier;
- a run that produced nothing recognisable degrades to an honest AdHocAnalysis naming the
  graph's real terminal status, never a crash.

`_execute_graph_run` itself is mocked here (its own correctness is `test_graph.py`'s job,
already exercised for real) -- this tests the new plumbing between a task and it.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import select, text

from src.core.db import get_session
from src.models.agent import AgentRun
from src.models.orchestration import Task
from src.orchestration import agent_invoker
from tests.orchestration_helpers import cleanup_run, seed_run_with_tasks


def _seed_task():
    run_id, keys = seed_run_with_tasks(
        [{"key": "strat", "capability": "strategy_research", "assigned_agent": "backtesting"}]
    )
    with get_session() as session:
        task = session.get(Task, keys["strat"])
        assert task is not None
        session.expunge(task)
    return run_id, task


def _cleanup_agent_runs(task) -> None:
    """T113b's handler creates real `agent_runs` rows keyed by `graph_thread_id=f"org-task-
    {task.id}"` -- an entirely separate table from the org `tasks`/`organization_runs` rows
    `cleanup_run` (orchestration_helpers) deletes, linked only by this naming convention, not a
    real FK. Found live: an earlier test run here left orphaned rows that `GET /agents/runs`
    (ordered by recency) then surfaced as "the most recent run" to an unrelated Cypress spec
    (`hitl_panel.cy.ts`), which got a real 404 instead of 403 forging an action against it."""
    thread_id = f"org-task-{task.id}"
    with get_session() as session:
        session.execute(
            text(
                "DELETE FROM agent_logs WHERE agent_run_id IN "
                "(SELECT id FROM agent_runs WHERE graph_thread_id = :tid)"
            ),
            {"tid": thread_id},
        )
        session.execute(
            text("DELETE FROM agent_runs WHERE graph_thread_id = :tid"), {"tid": thread_id}
        )
        session.commit()


def test_strategy_research_reads_back_the_graphs_real_final_output():
    run_id, task = _seed_task()
    try:

        def fake_execute_graph_run(*, thread_id, root_run_id, resume=False, research_context=None):
            now = datetime.now(UTC)
            with get_session() as session:
                root = session.get(AgentRun, root_run_id)
                assert root is not None
                root.status = "Completed"
                root.ended_at = now
                session.add(
                    AgentRun(
                        graph_thread_id=thread_id,
                        agent_name="deployment",
                        parent_run_id=root_run_id,
                        output_state={
                            "deployment_recommendation": {
                                "recommended_status": "PaperTrading",
                                "rationale": "backtest + evaluation both real and passing",
                            }
                        },
                        status="Completed",
                        started_at=now,
                        ended_at=now,
                    )
                )
                session.commit()

        with (
            patch("src.api.routers.agents._execute_graph_run", side_effect=fake_execute_graph_run),
            get_session() as session,
        ):
            artefact_type, payload, prov_extra = agent_invoker._strategy_research_handler(
                session, task, []
            )

        assert artefact_type == "DeploymentRecommendation"
        assert payload["recommended_status"] == "PaperTrading"
        assert prov_extra["tools_used"] == ["build_graph"]

        # A real AgentRun root row exists for this task's own thread_id.
        with get_session() as session:
            root = session.scalar(
                select(AgentRun).where(AgentRun.graph_thread_id == f"org-task-{task.id}")
            )
            assert root is not None
            assert root.status == "Completed"
    finally:
        _cleanup_agent_runs(task)
        cleanup_run(run_id)


def test_strategy_research_threads_the_research_context_into_the_graph():
    run_id, task = _seed_task()
    try:
        upstream_context = SimpleNamespace(
            artefact_type="ResearchContext",
            payload={"market_regime": "Bullish", "coverage": "full", "missing_inputs": []},
        )
        captured: dict = {}

        def fake_execute_graph_run(*, thread_id, root_run_id, resume=False, research_context=None):
            captured["research_context"] = research_context
            with get_session() as session:
                root = session.get(AgentRun, root_run_id)
                assert root is not None
                root.status = "Completed"
                root.ended_at = datetime.now(UTC)
                session.commit()

        with (
            patch("src.api.routers.agents._execute_graph_run", side_effect=fake_execute_graph_run),
            get_session() as session,
        ):
            agent_invoker._strategy_research_handler(session, task, [upstream_context])

        assert captured["research_context"] == upstream_context.payload
    finally:
        _cleanup_agent_runs(task)
        cleanup_run(run_id)


def test_strategy_research_degrades_honestly_when_nothing_recognizable_was_produced():
    run_id, task = _seed_task()
    try:

        def fake_execute_graph_run(*, thread_id, root_run_id, resume=False, research_context=None):
            # Simulates a halt/failure before any node produced a typed output.
            with get_session() as session:
                root = session.get(AgentRun, root_run_id)
                assert root is not None
                root.status = "Failed"
                root.ended_at = datetime.now(UTC)
                session.commit()

        with (
            patch("src.api.routers.agents._execute_graph_run", side_effect=fake_execute_graph_run),
            get_session() as session,
        ):
            artefact_type, payload, _ = agent_invoker._strategy_research_handler(session, task, [])

        assert artefact_type == "AdHocAnalysis"
        assert "Failed" in payload["answer"]
    finally:
        _cleanup_agent_runs(task)
        cleanup_run(run_id)


def test_strategy_research_degrades_honestly_on_a_schema_mismatch():
    """A real, defensive path: if a node's own output somehow doesn't re-validate against its
    registered schema, this must degrade to an honest AdHocAnalysis, never crash or silently
    persist a mismatched payload under the wrong type."""
    run_id, task = _seed_task()
    try:

        def fake_execute_graph_run(*, thread_id, root_run_id, resume=False, research_context=None):
            now = datetime.now(UTC)
            with get_session() as session:
                root = session.get(AgentRun, root_run_id)
                assert root is not None
                root.status = "Completed"
                root.ended_at = now
                session.add(
                    AgentRun(
                        graph_thread_id=thread_id,
                        agent_name="deployment",
                        parent_run_id=root_run_id,
                        # Missing the required `rationale` field -- deliberately invalid.
                        output_state={
                            "deployment_recommendation": {"recommended_status": "PaperTrading"}
                        },
                        status="Completed",
                        started_at=now,
                        ended_at=now,
                    )
                )
                session.commit()

        with (
            patch("src.api.routers.agents._execute_graph_run", side_effect=fake_execute_graph_run),
            get_session() as session,
        ):
            artefact_type, payload, _ = agent_invoker._strategy_research_handler(session, task, [])

        assert artefact_type == "AdHocAnalysis"
        assert "re-validation" in payload["answer"]
    finally:
        _cleanup_agent_runs(task)
        cleanup_run(run_id)
