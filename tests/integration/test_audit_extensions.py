"""REL-010 E10.8e: audit-query extensions (actor summary, export) and the observability
agent-run-duration wrapper (src/api/routers/audit.py) against the real FastAPI app + real
Postgres + the real Prometheus Histogram already observed by src/api/routers/agents.py's
`_execute_graph_run`.
"""

from fastapi.testclient import TestClient

from src.api.main import app
from src.core.audit import write_audit_entry
from src.core.db import get_session
from src.core.security import ROLE_READ_ONLY_AUDITOR, ROLE_SYSTEM_ADMINISTRATOR
from src.observability.metrics import AGENT_RUN_DURATION_SECONDS
from tests.auth_helpers import auth_header, cleanup_user, create_authenticated_user

client = TestClient(app)

_ACTOR_ID = "e10-8-audit-extensions-test-actor"


def _seed_entries() -> None:
    with get_session() as session:
        write_audit_entry(
            session,
            actor_type="Human",
            actor_id=_ACTOR_ID,
            action="TEST_ACTION_ONE",
            entity_type="TestEntity",
        )
        write_audit_entry(
            session,
            actor_type="Human",
            actor_id=_ACTOR_ID,
            action="TEST_ACTION_ONE",
            entity_type="TestEntity",
        )
        write_audit_entry(
            session,
            actor_type="Human",
            actor_id=_ACTOR_ID,
            action="TEST_ACTION_TWO",
            entity_type="TestEntity",
        )
        session.commit()


def test_actor_summary_requires_the_gated_role():
    response = client.get(f"/api/v1/audit/actors/{_ACTOR_ID}/summary")
    assert response.status_code == 401


def test_actor_summary_aggregates_real_entries():
    _seed_entries()
    user_id, token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        response = client.get(
            f"/api/v1/audit/actors/{_ACTOR_ID}/summary", headers=auth_header(token)
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total_entries"] >= 3
        assert body["action_counts"]["TEST_ACTION_ONE"] >= 2
        assert body["action_counts"]["TEST_ACTION_TWO"] >= 1
    finally:
        cleanup_user(user_id)


def test_actor_summary_404s_for_an_actor_with_no_entries():
    user_id, token = create_authenticated_user(ROLE_READ_ONLY_AUDITOR)
    try:
        response = client.get(
            "/api/v1/audit/actors/no-entries-for-this-actor-ever/summary",
            headers=auth_header(token),
        )
        assert response.status_code == 404
    finally:
        cleanup_user(user_id)


def test_export_ndjson_returns_real_rows():
    _seed_entries()
    user_id, token = create_authenticated_user(ROLE_READ_ONLY_AUDITOR)
    try:
        response = client.get(
            "/api/v1/audit/export",
            params={"export_format": "ndjson", "entity_type": "TestEntity", "limit": 10},
            headers=auth_header(token),
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/x-ndjson")
        lines = [line for line in response.text.splitlines() if line]
        assert len(lines) > 0
    finally:
        cleanup_user(user_id)


def test_export_csv_returns_a_real_header_row():
    _seed_entries()
    user_id, token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        response = client.get(
            "/api/v1/audit/export",
            params={"export_format": "csv", "entity_type": "TestEntity", "limit": 10},
            headers=auth_header(token),
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert response.text.splitlines()[0].startswith("id,")
    finally:
        cleanup_user(user_id)


def test_agent_run_durations_reads_the_real_prometheus_histogram():
    AGENT_RUN_DURATION_SECONDS.labels(agent_name="e10_8_test_agent").observe(1.5)
    user_id, token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        response = client.get(
            "/api/v1/observability/agent-run-durations", headers=auth_header(token)
        )
        assert response.status_code == 200
        body = response.json()
        entry = next(row for row in body if row["agent_name"] == "e10_8_test_agent")
        assert entry["run_count"] >= 1
        assert entry["avg_duration_seconds"] > 0
    finally:
        cleanup_user(user_id)
