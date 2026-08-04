"""Per-agent control API integration test (REL-019 E19.2, ADR 11):
GET/PUT /api/v1/agents/control against the real FastAPI app + real Postgres
`agent_control_state` table. Covers the registry-listing shape, the real toggle round-trip, the
Audit Agent's hardcoded non-disableable guard (Business Rule 5), RBAC, and audit-trail evidence
-- not the graph-level halt-on-entry mechanism itself, which is a real LLM-costing end-to-end run
and is instead covered by a direct unit test against `src.agents.control` + `build_graph()`.
"""

import uuid

from fastapi.testclient import TestClient

from src.agents.control import AUDIT_AGENT_NAME, KNOWN_AGENTS
from src.api.main import app
from src.core.db import get_session
from src.core.security import ROLE_READ_ONLY_AUDITOR, ROLE_RISK_MANAGER
from src.models.agent import AgentControlState
from tests.auth_helpers import auth_header, cleanup_user, create_authenticated_user

client = TestClient(app)


def _cleanup_control_row(agent_name: str) -> None:
    with get_session() as session:
        session.query(AgentControlState).filter(AgentControlState.agent_name == agent_name).delete()
        session.commit()


def test_control_list_covers_the_full_real_agent_registry_and_defaults_to_enabled():
    response = client.get("/api/v1/agents/control")
    assert response.status_code == 200
    body = {entry["agent_name"]: entry for entry in response.json()}
    assert len(body) == len(KNOWN_AGENTS)
    # An agent with no row in agent_control_state is genuinely enabled (fail-open default),
    # not a placeholder -- assert this for a real graph-node agent that no other test disables.
    assert body["backtesting"]["enabled"] is True
    assert body["backtesting"]["enforced"] is True
    assert body["backtesting"]["kind"] == "graph_node"


def test_toggle_round_trips_and_persists_a_real_row():
    agent_name = "risk_manager"
    user_id, token = create_authenticated_user(ROLE_RISK_MANAGER)
    try:
        disable = client.put(
            f"/api/v1/agents/control/{agent_name}",
            json={"enabled": False, "reason": "integration test disable"},
            headers=auth_header(token),
        )
        assert disable.status_code == 200
        body = disable.json()
        assert body["enabled"] is False
        assert body["reason"] == "integration test disable"
        assert body["updated_by"] is not None

        listed = client.get("/api/v1/agents/control").json()
        entry = next(e for e in listed if e["agent_name"] == agent_name)
        assert entry["enabled"] is False
        assert entry["reason"] == "integration test disable"

        enable = client.put(
            f"/api/v1/agents/control/{agent_name}",
            json={"enabled": True, "reason": None},
            headers=auth_header(token),
        )
        assert enable.status_code == 200
        assert enable.json()["enabled"] is True
    finally:
        _cleanup_control_row(agent_name)
        cleanup_user(user_id)


def test_toggle_requires_hitl_role():
    user_id, token = create_authenticated_user(ROLE_READ_ONLY_AUDITOR)
    try:
        response = client.put(
            "/api/v1/agents/control/backtesting",
            json={"enabled": False, "reason": "should be forbidden"},
            headers=auth_header(token),
        )
        assert response.status_code == 403
    finally:
        cleanup_user(user_id)
    listed = client.get("/api/v1/agents/control").json()
    entry = next(e for e in listed if e["agent_name"] == "backtesting")
    assert entry["enabled"] is True  # the forbidden request must not have changed real state


def test_audit_agent_cannot_be_disabled():
    """Business Rule 5 (immutable AI/trade audit trail) -- ADR 11 hardcodes this refusal in
    src.agents.control.set_agent_enabled rather than leaving it to operator discipline."""
    user_id, token = create_authenticated_user(ROLE_RISK_MANAGER)
    try:
        response = client.put(
            f"/api/v1/agents/control/{AUDIT_AGENT_NAME}",
            json={"enabled": False, "reason": "attempting to silence the audit trail"},
            headers=auth_header(token),
        )
        assert response.status_code == 400
    finally:
        cleanup_user(user_id)
    listed = client.get("/api/v1/agents/control").json()
    entry = next(e for e in listed if e["agent_name"] == AUDIT_AGENT_NAME)
    assert entry["enabled"] is True


def test_toggle_unknown_agent_name_is_a_real_404():
    user_id, token = create_authenticated_user(ROLE_RISK_MANAGER)
    try:
        response = client.put(
            f"/api/v1/agents/control/not-a-real-agent-{uuid.uuid4().hex[:8]}",
            json={"enabled": False, "reason": None},
            headers=auth_header(token),
        )
        assert response.status_code == 404
    finally:
        cleanup_user(user_id)
