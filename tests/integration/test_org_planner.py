"""CEO planner integration test (spec T030, US1, SC-015).

Uses a mocked ``complete`` (canned plan JSON) so the planner -> deterministic validation ->
persistence path is exercised without a live LLM, matching this codebase's mocked-LLM node-test
convention. Runs against the real Postgres.
"""

import json
import uuid
from unittest.mock import MagicMock, patch

from src.core.db import get_session
from src.models.orchestration import (
    OrganizationalDecision,
    OrganizationalEvent,
    OrganizationalPlan,
    OrganizationRun,
    Task,
    TaskDependency,
)
from src.orchestration import run_manager
from src.orchestration.enums import RunSource, RunStatus
from tests.orchestration_helpers import cleanup_run

_VALID_PLAN = {
    "can_plan": True,
    "objective_classification": "swing_research",
    "departments": ["Market Intelligence", "Research"],
    "approval_required": True,
    "tasks": [
        {
            "key": "t1",
            "objective": "assess the market",
            "capability": "market_analysis",
            "assigned_agent": "market_analyst",
            "priority": 1,
            "expected_output": "MarketContext",
            "depends_on": [],
        },
        {
            "key": "t2",
            "objective": "ingest news",
            "capability": "news_ingestion",
            "assigned_agent": "news_agent",
            "priority": 1,
            "expected_output": "NewsDigest",
            "depends_on": [],
        },
        {
            "key": "t3",
            "objective": "score sentiment",
            "capability": "sentiment_analysis",
            "assigned_agent": "sentiment_agent",
            "priority": 2,
            "expected_output": "SentimentReport",
            "depends_on": ["t2"],
        },
    ],
}


def _fake_response(payload: dict) -> MagicMock:
    r = MagicMock()
    r.choices[0].message.content = json.dumps(payload)
    return r


_TERMINAL = (RunStatus.WAITING.value, RunStatus.CANNOT_PLAN.value, RunStatus.FAILED.value)


def _run_and_wait(objective: str, response: MagicMock, timeout: float = 20.0) -> uuid.UUID:
    import time

    # The planner runs in a detached daemon thread, so the patches must stay active until the
    # run reaches a terminal state. `query_org_memory` is imported inside generate_plan, so it
    # is patched at its source module.
    with (
        patch("src.orchestration.planner.complete", return_value=response),
        patch("src.memory.organization_memory.query_org_memory", return_value=[]),
    ):
        with get_session() as session:
            run = run_manager.create_run(
                session,
                objective=objective,
                source=RunSource.API,
                requested_by="test@example.invalid",
            )
            run_id = run.id
        deadline = time.time() + timeout
        while time.time() < deadline:
            with get_session() as s:
                r = s.get(OrganizationRun, run_id)
                if r is not None and r.status in _TERMINAL:
                    return run_id
            time.sleep(0.4)
    return run_id


def _cleanup(run_id: uuid.UUID) -> None:
    cleanup_run(run_id)


def test_valid_objective_produces_a_persisted_validated_plan():
    run_id = _run_and_wait(
        "Find low-risk swing opportunities for tomorrow", _fake_response(_VALID_PLAN)
    )
    try:
        with get_session() as session:
            run = session.get(OrganizationRun, run_id)
            assert run is not None and run.plan_id is not None
            plan = session.get(OrganizationalPlan, run.plan_id)
            assert plan is not None
            assert plan.objective_classification == "swing_research"
            tasks = session.query(Task).filter(Task.plan_id == plan.id).all()
            assert len(tasks) == 3
            assert {t.assigned_agent for t in tasks} == {
                "market_analyst",
                "news_agent",
                "sentiment_agent",
            }
            deps = session.query(TaskDependency).filter(TaskDependency.plan_id == plan.id).all()
            assert len(deps) == 1
            events = (
                session.query(OrganizationalEvent)
                .filter(OrganizationalEvent.run_id == run_id)
                .all()
            )
            assert any(e.event_type == "organization.plan.created" for e in events)
    finally:
        _cleanup(run_id)


def test_two_different_objectives_produce_distinct_plans():
    plan_b = json.loads(json.dumps(_VALID_PLAN))
    # Deliberately not "portfolio_analysis" (or any of the other US8 ad-hoc-analysis
    # classifications) -- those now deterministically grow the plan via
    # planner.ensure_adhoc_scaffold, which would break this test's single-task assertion below
    # for a reason unrelated to what this test actually checks (two objectives -> two distinct,
    # independently-sized plans).
    plan_b["objective_classification"] = "single_task_smoke_test"
    plan_b["tasks"] = [plan_b["tasks"][0]]  # single-task plan
    run_a = _run_and_wait("Research a momentum strategy", _fake_response(_VALID_PLAN))
    run_b = _run_and_wait("Analyse my portfolio concentration", _fake_response(plan_b))
    try:
        with get_session() as session:
            pa = session.get(OrganizationalPlan, session.get(OrganizationRun, run_a).plan_id)
            pb = session.get(OrganizationalPlan, session.get(OrganizationRun, run_b).plan_id)
            assert pa.id != pb.id
            assert pb.objective_classification == "single_task_smoke_test"
            assert session.query(Task).filter(Task.plan_id == pb.id).count() == 1
    finally:
        _cleanup(run_a)
        _cleanup(run_b)


def test_unservable_objective_is_recorded_as_cannot_plan_not_fabricated():
    run_id = _run_and_wait(
        "Trade crypto perpetuals on Binance",
        _fake_response({"can_plan": False, "reason": "no agent can trade crypto perpetuals"}),
    )
    try:
        with get_session() as session:
            run = session.get(OrganizationRun, run_id)
            assert run is not None and run.status == RunStatus.CANNOT_PLAN.value
            assert run.plan_id is None
            assert (
                session.query(OrganizationalPlan)
                .filter(OrganizationalPlan.run_id == run_id)
                .count()
                == 0
            )
            decisions = (
                session.query(OrganizationalDecision)
                .filter(OrganizationalDecision.run_id == run_id)
                .all()
            )
            assert len(decisions) == 1 and decisions[0].decision_type == "cannot_plan"
    finally:
        _cleanup(run_id)
