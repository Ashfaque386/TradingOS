"""Agent Console API integration test (Phase 4 Epic E4.3): the read/topology/prompt-registry
endpoints wired in src/api/routers/agents.py, against the real FastAPI app + real
prompt_registry.py files on disk. Does NOT trigger a real graph run (POST /research/trigger) --
that's covered by hand-verified end-to-end runs elsewhere in this session (real LLM calls that
can take 10+ minutes here via the Ollama fallback path, impractical for a routine test run);
this focuses on the deterministic, fast parts: topology introspection, run history reads, and a
real, reversible prompt hot-swap.

REL-011 E10.11.0: POST /research/trigger and PUT /prompts/{slug}/active-version were found with
NO auth dependency at all during frontend-completeness research (not even get_current_user) --
both are now real, SA/PM/RM-gated. The 401/403 boundary tests below never reach the real
handler body (require_role runs first), so they're safe to run without triggering a real graph
run or an unintended prompt swap.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from src.agents.control import KNOWN_AGENTS
from src.agents.prompt_registry import get_active_prompt
from src.api.main import app
from src.core.db import get_session
from src.core.security import ROLE_READ_ONLY_AUDITOR, ROLE_RISK_MANAGER
from src.models.agent import AgentRun
from tests.auth_helpers import auth_header, cleanup_user, create_authenticated_user

client = TestClient(app)


def test_graph_topology_reflects_the_real_compiled_graph():
    response = client.get("/api/v1/agents/graph")
    assert response.status_code == 200
    body = response.json()
    node_ids = {n["id"] for n in body["nodes"]}
    assert {
        "ceo_agent",
        "market_analyst",
        "strategy_generator",
        "python_code_generator",
        "python_validator",
        "backtesting",
        "evaluator",
        "optimization",
        "risk_manager",
        "deployment",
    } <= node_ids
    retry_edges = [
        e
        for e in body["edges"]
        if e["source"] == "python_validator" and e["target"] == "python_code_generator"
    ]
    assert retry_edges and retry_edges[0]["conditional"] is True


def test_runs_list_returns_only_root_runs():
    response = client.get("/api/v1/agents/runs")
    assert response.status_code == 200
    for run in response.json():
        assert run["agent_name"] == "TradingOSGraph"


def test_prompts_list_matches_the_real_registry_file():
    response = client.get("/api/v1/agents/prompts")
    assert response.status_code == 200
    slugs = {p["agent_slug"] for p in response.json()}
    assert {
        "ceo_agent",
        "market_analyst_agent",
        "strategy_generator_agent",
        "python_code_generator_agent",
        "python_validator_agent",
    } <= slugs


def test_prompt_version_hot_swap_is_real_and_reversible():
    slug = "python_code_generator_agent"
    original = client.get("/api/v1/agents/prompts").json()
    original_entry = next(p for p in original if p["agent_slug"] == slug)
    original_version = original_entry["active_version"]
    assert original_version in original_entry["available_versions"]
    other_version = next(v for v in original_entry["available_versions"] if v != original_version)

    user_id, token = create_authenticated_user(ROLE_RISK_MANAGER)
    try:
        swap_response = client.put(
            f"/api/v1/agents/prompts/{slug}/active-version",
            json={"version": other_version},
            headers=auth_header(token),
        )
        assert swap_response.status_code == 200
        assert swap_response.json()["active_version"] == other_version
        # get_active_prompt() re-reads registry.yaml fresh -- confirms the swap actually took
        # effect on the real hot-reload path every agent node calls, not just the API response.
        content_at_other_version = get_active_prompt(slug)

        version_content_response = client.get(
            f"/api/v1/agents/prompts/{slug}/versions/{other_version}"
        )
        assert version_content_response.status_code == 200
        assert version_content_response.json()["content"] == content_at_other_version
    finally:
        restore_response = client.put(
            f"/api/v1/agents/prompts/{slug}/active-version",
            json={"version": original_version},
            headers=auth_header(token),
        )
        assert restore_response.status_code == 200
        assert restore_response.json()["active_version"] == original_version
        cleanup_user(user_id)


def test_prompt_active_version_swap_requires_authentication():
    response = client.put(
        "/api/v1/agents/prompts/python_code_generator_agent/active-version", json={"version": 1}
    )
    assert response.status_code == 401


def test_prompt_active_version_swap_requires_the_gated_role():
    user_id, token = create_authenticated_user(ROLE_READ_ONLY_AUDITOR)
    try:
        response = client.put(
            "/api/v1/agents/prompts/python_code_generator_agent/active-version",
            json={"version": 1},
            headers=auth_header(token),
        )
        assert response.status_code == 403
    finally:
        cleanup_user(user_id)


def test_research_trigger_requires_authentication():
    response = client.post("/api/v1/agents/research/trigger")
    assert response.status_code == 401


def test_research_trigger_requires_the_gated_role():
    user_id, token = create_authenticated_user(ROLE_READ_ONLY_AUDITOR)
    try:
        response = client.post("/api/v1/agents/research/trigger", headers=auth_header(token))
        assert response.status_code == 403
    finally:
        cleanup_user(user_id)


# --- Agent detail (API-026, REL-062) --------------------------------------------------------


def test_agent_detail_404s_for_an_unknown_agent_id():
    response = client.get("/api/v1/agents/not-a-real-agent-id")
    assert response.status_code == 404


def test_agent_detail_returns_one_instance_for_a_unique_agent_id():
    response = client.get("/api/v1/agents/AGT-001")
    assert response.status_code == 200
    body = response.json()
    assert body["agent_id"] == "AGT-001"
    assert len(body["instances"]) == 1
    assert body["instances"][0]["name"] == "ceo_agent"
    assert body["instances"][0]["enabled"] is True  # fail-open default: no control row seeded


def test_agent_detail_surfaces_both_instances_for_the_real_agt_009_duplicate():
    # A real data quirk in KNOWN_AGENTS (src/agents/control.py), not a test artifact: AGT-009 is
    # shared by memory_ingest (graph-node incarnation) and memory_agent (scheduled incarnation).
    matches = [a for a in KNOWN_AGENTS if a.agent_id == "AGT-009"]
    assert len(matches) == 2

    response = client.get("/api/v1/agents/AGT-009")
    assert response.status_code == 200
    names = {inst["name"] for inst in response.json()["instances"]}
    assert names == {"memory_ingest", "memory_agent"}


def test_agent_detail_reports_the_most_recent_run_for_that_agent_name():
    run_id = uuid.uuid4()
    with get_session() as session:
        session.add(
            AgentRun(
                id=run_id,
                graph_thread_id=str(uuid.uuid4()),
                agent_name="ceo_agent",
                status="Completed",
                started_at=datetime.now(UTC),
            )
        )
        session.commit()
    try:
        response = client.get("/api/v1/agents/AGT-001")
        assert response.status_code == 200
        instance = response.json()["instances"][0]
        assert instance["last_run_status"] == "Completed"
        assert instance["last_run_at"] is not None
    finally:
        with get_session() as session:
            session.query(AgentRun).filter(AgentRun.id == run_id).delete()
            session.commit()


# --- LangSmith trace URL surfaced on run detail (API-073, REL-062) -------------------------


def test_run_detail_serializes_the_real_langsmith_trace_url_column():
    run_id = uuid.uuid4()
    marker_url = f"https://smith.langchain.com/trace/{uuid.uuid4()}"
    with get_session() as session:
        session.add(
            AgentRun(
                id=run_id,
                graph_thread_id=str(uuid.uuid4()),
                agent_name="TradingOSGraph",
                status="Completed",
                started_at=datetime.now(UTC),
                langsmith_trace_url=marker_url,
            )
        )
        session.commit()
    try:
        response = client.get(f"/api/v1/agents/runs/{run_id}")
        assert response.status_code == 200
        assert response.json()["langsmith_trace_url"] == marker_url
    finally:
        with get_session() as session:
            session.query(AgentRun).filter(AgentRun.id == run_id).delete()
            session.commit()


def test_run_detail_langsmith_trace_url_is_none_when_tracing_was_never_configured():
    run_id = uuid.uuid4()
    with get_session() as session:
        session.add(
            AgentRun(
                id=run_id,
                graph_thread_id=str(uuid.uuid4()),
                agent_name="TradingOSGraph",
                status="Completed",
                started_at=datetime.now(UTC),
            )
        )
        session.commit()
    try:
        response = client.get(f"/api/v1/agents/runs/{run_id}")
        assert response.status_code == 200
        assert response.json()["langsmith_trace_url"] is None
    finally:
        with get_session() as session:
            session.query(AgentRun).filter(AgentRun.id == run_id).delete()
            session.commit()


# REL-068: GET /agents/analytics/summary and GET /agents/analytics/trend -- real aggregate
# stats over real AgentRun rows. Seeded with a uuid-marked agent_name so assertions are
# deterministic regardless of whatever real runs this shared dev DB already has (confirmed
# non-empty -- compliance/python_code_generator/etc. already have dozens of real rows).


def test_analytics_summary_reports_real_success_rate_and_duration_for_a_seeded_agent():
    marker_agent = f"cy-analytics-agent-{uuid.uuid4().hex[:8]}"
    run_ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
    now = datetime.now(UTC)
    with get_session() as session:
        session.add_all(
            [
                AgentRun(
                    id=run_ids[0],
                    graph_thread_id=str(uuid.uuid4()),
                    agent_name=marker_agent,
                    status="Completed",
                    started_at=now,
                    ended_at=now + timedelta(seconds=10),
                ),
                AgentRun(
                    id=run_ids[1],
                    graph_thread_id=str(uuid.uuid4()),
                    agent_name=marker_agent,
                    status="Completed",
                    started_at=now,
                    ended_at=now + timedelta(seconds=30),
                ),
                AgentRun(
                    id=run_ids[2],
                    graph_thread_id=str(uuid.uuid4()),
                    agent_name=marker_agent,
                    status="Failed",
                    started_at=now,
                    ended_at=now + timedelta(seconds=5),
                ),
            ]
        )
        session.commit()
    try:
        response = client.get("/api/v1/agents/analytics/summary?days=1")
        assert response.status_code == 200
        rows = {r["agent_name"]: r for r in response.json()}
        assert marker_agent in rows
        row = rows[marker_agent]
        assert row["total_runs"] == 3
        assert row["completed"] == 2
        assert row["failed"] == 1
        assert row["success_rate"] == pytest.approx(2 / 3)
        assert row["avg_duration_seconds"] == pytest.approx(20.0)
    finally:
        with get_session() as session:
            session.query(AgentRun).filter(AgentRun.id.in_(run_ids)).delete(
                synchronize_session=False
            )
            session.commit()


def test_analytics_summary_days_param_excludes_runs_outside_the_window():
    marker_agent = f"cy-analytics-old-{uuid.uuid4().hex[:8]}"
    run_id = uuid.uuid4()
    old_start = datetime.now(UTC) - timedelta(days=90)
    with get_session() as session:
        session.add(
            AgentRun(
                id=run_id,
                graph_thread_id=str(uuid.uuid4()),
                agent_name=marker_agent,
                status="Completed",
                started_at=old_start,
                ended_at=old_start + timedelta(seconds=1),
            )
        )
        session.commit()
    try:
        response = client.get("/api/v1/agents/analytics/summary?days=1")
        assert response.status_code == 200
        assert marker_agent not in {r["agent_name"] for r in response.json()}
    finally:
        with get_session() as session:
            session.query(AgentRun).filter(AgentRun.id == run_id).delete()
            session.commit()


def test_analytics_trend_buckets_real_runs_by_day():
    marker_thread = f"cy-trend-{uuid.uuid4().hex[:8]}"
    run_ids = [uuid.uuid4(), uuid.uuid4()]
    now = datetime.now(UTC)
    with get_session() as session:
        session.add_all(
            [
                AgentRun(
                    id=run_ids[0],
                    graph_thread_id=marker_thread,
                    agent_name="TradingOSGraph",
                    status="Completed",
                    started_at=now,
                    ended_at=now + timedelta(seconds=1),
                ),
                AgentRun(
                    id=run_ids[1],
                    graph_thread_id=marker_thread,
                    agent_name="TradingOSGraph",
                    status="Failed",
                    started_at=now,
                    ended_at=now + timedelta(seconds=1),
                ),
            ]
        )
        session.commit()
    try:
        response = client.get("/api/v1/agents/analytics/trend?days=1")
        assert response.status_code == 200
        points = response.json()
        today = [p for p in points if p["date"] == now.date().isoformat()]
        assert len(today) == 1
        assert today[0]["total_runs"] >= 2
        assert today[0]["completed"] >= 1
        assert today[0]["failed"] >= 1
    finally:
        with get_session() as session:
            session.query(AgentRun).filter(AgentRun.id.in_(run_ids)).delete(
                synchronize_session=False
            )
            session.commit()
