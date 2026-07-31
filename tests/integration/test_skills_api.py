"""Skill Admin API integration tests (REL-010 E10.6, API-025..032) against the real FastAPI app
+ real Postgres. Mirrors tests/integration/test_audit_api.py's RBAC-testing style.
"""

from fastapi.testclient import TestClient

from src.agents.tools.registry import get_skill_registry
from src.api.main import app
from src.core.security import ROLE_READ_ONLY_AUDITOR, ROLE_SYSTEM_ADMINISTRATOR
from tests.auth_helpers import auth_header, cleanup_user, create_authenticated_user

client = TestClient(app)
_TARGET_SKILL = "fetch_portfolio_status"


def test_list_and_get_skill_is_unauthenticated_read_only():
    get_skill_registry()  # ensure DB rows exist
    list_response = client.get("/api/v1/skills")
    assert list_response.status_code == 200
    names = {row["name"] for row in list_response.json()}
    assert _TARGET_SKILL in names

    get_response = client.get(f"/api/v1/skills/{_TARGET_SKILL}")
    assert get_response.status_code == 200
    assert get_response.json()["name"] == _TARGET_SKILL

    schema_response = client.get(f"/api/v1/skills/{_TARGET_SKILL}/schema")
    assert schema_response.status_code == 200


def test_get_unknown_skill_is_404():
    response = client.get("/api/v1/skills/does-not-exist-skill")
    assert response.status_code == 404


def test_enable_disable_requires_system_administrator_role():
    user_id, token = create_authenticated_user(ROLE_READ_ONLY_AUDITOR)
    try:
        response = client.post(
            f"/api/v1/skills/{_TARGET_SKILL}/disable", headers=auth_header(token)
        )
        assert response.status_code == 403
    finally:
        cleanup_user(user_id)


def test_unauthenticated_disable_is_rejected():
    response = client.post(f"/api/v1/skills/{_TARGET_SKILL}/disable")
    assert response.status_code == 401


def test_system_administrator_can_disable_then_enable_a_real_skill():
    get_skill_registry()
    user_id, token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    headers = auth_header(token)

    try:
        disable_response = client.post(f"/api/v1/skills/{_TARGET_SKILL}/disable", headers=headers)
        assert disable_response.status_code == 200
        assert disable_response.json()["is_enabled"] is False

        get_response = client.get(f"/api/v1/skills/{_TARGET_SKILL}")
        assert get_response.json()["is_enabled"] is False

        enable_response = client.post(f"/api/v1/skills/{_TARGET_SKILL}/enable", headers=headers)
        assert enable_response.status_code == 200
        assert enable_response.json()["is_enabled"] is True
    finally:
        cleanup_user(user_id)
        get_skill_registry().enable(_TARGET_SKILL, persist=True)  # leave state clean either way


def test_grant_and_revoke_agent_skill_map():
    get_skill_registry()
    user_id, token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    headers = auth_header(token)

    try:
        grant_response = client.post(
            "/api/v1/skills/agent-map",
            json={"agent_name": "TestAgent", "skill_name": _TARGET_SKILL},
            headers=headers,
        )
        assert grant_response.status_code == 201
        body = grant_response.json()
        assert body["agent_name"] == "TestAgent"
        assert body["skill_name"] == _TARGET_SKILL

        list_response = client.get("/api/v1/skills/agent-map", headers=headers)
        assert any(row["id"] == body["id"] for row in list_response.json())

        duplicate_response = client.post(
            "/api/v1/skills/agent-map",
            json={"agent_name": "TestAgent", "skill_name": _TARGET_SKILL},
            headers=headers,
        )
        assert duplicate_response.status_code == 409

        revoke_response = client.delete(f"/api/v1/skills/agent-map/{body['id']}", headers=headers)
        assert revoke_response.status_code == 204
    finally:
        cleanup_user(user_id)
