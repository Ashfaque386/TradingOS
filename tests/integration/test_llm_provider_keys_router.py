"""REL-021 E21.1: LLM provider key write/delete endpoints (src/api/routers/settings.py) against
the real FastAPI app + real dev Vault -- same shape as test_broker_config_router.py, plus proof
that a real HTTP write is picked up by the real resolve_api_key() precedence a real LLM call uses,
with no process restart.
"""

import uuid

from fastapi.testclient import TestClient

from src.agents.llm_router import resolve_api_key
from src.api.main import app
from src.core import vault
from src.core.config import get_settings
from src.core.security import ROLE_READ_ONLY_AUDITOR, ROLE_SYSTEM_ADMINISTRATOR
from tests.auth_helpers import auth_header, cleanup_user, create_authenticated_user

client = TestClient(app)


def test_set_key_requires_system_administrator_role():
    user_id, token = create_authenticated_user(ROLE_READ_ONLY_AUDITOR)
    try:
        response = client.post(
            "/api/v1/settings/llm-provider-keys/openai",
            json={"api_key": "x"},
            headers=auth_header(token),
        )
        assert response.status_code == 403
    finally:
        cleanup_user(user_id)


def test_unauthenticated_set_key_is_rejected():
    response = client.post("/api/v1/settings/llm-provider-keys/openai", json={"api_key": "x"})
    assert response.status_code == 401


def test_unknown_provider_is_rejected_with_422():
    user_id, token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        response = client.post(
            "/api/v1/settings/llm-provider-keys/not-a-real-provider",
            json={"api_key": "x"},
            headers=auth_header(token),
        )
        assert response.status_code == 422
    finally:
        cleanup_user(user_id)


def test_ollama_is_rejected_since_it_never_needs_a_key():
    user_id, token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        response = client.post(
            "/api/v1/settings/llm-provider-keys/ollama",
            json={"api_key": "x"},
            headers=auth_header(token),
        )
        assert response.status_code == 422
    finally:
        cleanup_user(user_id)


def test_system_administrator_can_write_and_delete_a_real_provider_key():
    """Uses a real provider id (deepseek, validated against LLM_PROVIDER_IDS, unlike broker
    names which aren't validated) -- writes a real marker key via the real HTTP endpoint, reads
    it back directly from Vault to prove the write landed, deletes it via the endpoint, then
    restores whatever the real .env-sourced key was (or leaves it absent if there wasn't one),
    matching test_vault.py's own established restore discipline for shared provider slots."""
    user_id, token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    provider = "deepseek"
    marker_key = f"e21-test-key-{uuid.uuid4().hex[:8]}"
    try:
        response = client.post(
            f"/api/v1/settings/llm-provider-keys/{provider}",
            json={"api_key": marker_key},
            headers=auth_header(token),
        )
        assert response.status_code == 204

        assert vault.read_llm_provider_key(provider) == marker_key

        delete_response = client.delete(
            f"/api/v1/settings/llm-provider-keys/{provider}", headers=auth_header(token)
        )
        assert delete_response.status_code == 204
        assert vault.read_llm_provider_key(provider) is None
    finally:
        real_settings = get_settings()
        if real_settings.deepseek_api_key:
            vault.write_llm_provider_key(provider, real_settings.deepseek_api_key)
        else:
            vault.delete_llm_provider_key(provider)
        cleanup_user(user_id)


def test_a_real_written_key_is_used_by_the_real_llm_call_path_with_no_restart():
    """The actual REL-021 exit criterion: write via the real HTTP endpoint, then confirm
    resolve_api_key() -- the exact function every real LLM call goes through -- picks up the new
    value immediately, proving no process restart is needed."""
    user_id, token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    provider = "gemini"
    marker_key = f"e21-live-path-{uuid.uuid4().hex[:8]}"
    try:
        response = client.post(
            f"/api/v1/settings/llm-provider-keys/{provider}",
            json={"api_key": marker_key},
            headers=auth_header(token),
        )
        assert response.status_code == 204

        assert resolve_api_key(provider, get_settings()) == marker_key
    finally:
        real_settings = get_settings()
        if real_settings.gemini_api_key:
            vault.write_llm_provider_key(provider, real_settings.gemini_api_key)
        else:
            vault.delete_llm_provider_key(provider)
        cleanup_user(user_id)


def test_integrations_status_reflects_a_real_vault_write_immediately():
    """Proves GET /integrations is Vault-aware, not just .env-aware -- the other half of the
    exit criterion (the Settings page's own status grid updates on write, not just the LLM call
    path)."""
    user_id, token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    provider = "opencode"
    marker_key = f"e21-status-{uuid.uuid4().hex[:8]}"
    try:
        write_response = client.post(
            f"/api/v1/settings/llm-provider-keys/{provider}",
            json={"api_key": marker_key},
            headers=auth_header(token),
        )
        assert write_response.status_code == 204

        status_response = client.get("/api/v1/settings/integrations")
        assert status_response.status_code == 200
        opencode_status = next(
            p for p in status_response.json()["llm_providers"] if p["name"] == "OpenCode Zen"
        )
        assert opencode_status["configured"] is True
        assert opencode_status["masked_hint"] == "••••" + marker_key[-4:]
    finally:
        real_settings = get_settings()
        if real_settings.opencode_api_key:
            vault.write_llm_provider_key(provider, real_settings.opencode_api_key)
        else:
            vault.delete_llm_provider_key(provider)
        cleanup_user(user_id)
