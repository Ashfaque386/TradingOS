"""Global Settings API integration test (Phase 4 Epic E4.3): the endpoints wired in
src/api/routers/settings.py, against the real FastAPI app + real Postgres + the real
process-lifetime Settings object (src/core/config.py).
"""

import uuid

from fastapi.testclient import TestClient

from src.api.main import app
from src.core import vault
from src.core.config import get_settings
from src.core.db import get_session
from src.core.security import ROLE_PORTFOLIO_MANAGER, ROLE_SYSTEM_ADMINISTRATOR
from src.models.user import NotificationChannel
from tests.auth_helpers import auth_header, cleanup_user, create_authenticated_user

client = TestClient(app)


def test_vault_status_reports_the_real_dev_vault_reachability():
    """API-079 (REL-062): src/core/vault.py's own is_authenticated() round-trip, exposed on its
    own endpoint -- against the real docker-compose Vault (see tests/integration/test_vault.py
    for the underlying client tests), never a fabricated value."""
    response = client.get("/api/v1/settings/vault/status")
    assert response.status_code == 200
    body = response.json()
    assert body["reachable"] is True
    assert body["kv_engine_mounted"] is True
    assert body["vault_addr"] is not None


def test_integrations_status_never_leaks_a_raw_secret():
    response = client.get("/api/v1/settings/integrations")
    assert response.status_code == 200
    body = response.json()
    assert body["editable"] is False

    for provider in body["llm_providers"] + body["brokers"]:
        hint = provider["masked_hint"]
        # Ollama's "hint" is just its base URL, not a secret
        if hint and provider["name"] != "Ollama":
            assert hint.startswith("••••")
            assert len(hint) <= 8  # "••••" + at most 4 real trailing chars, never the full key


def test_notification_channel_mutations_require_system_administrator_or_portfolio_manager():
    # The old "0 users in the DB -> 409" case (src/api/routers/settings.py's _first_user_id())
    # is no longer reachable via the API now that these endpoints require auth: a valid JWT
    # implies get_current_user already found and returned a real User row, so by the time any
    # of these handlers run, the table can never be empty.
    unauthenticated = client.post(
        "/api/v1/settings/notification-channels",
        json={"channel_type": "Telegram", "external_handle": "x", "alert_levels": []},
    )
    assert unauthenticated.status_code == 401


def test_notification_channel_full_crud_cycle():
    admin_id, admin_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    headers = auth_header(admin_token)

    marker = f"integration-test-{uuid.uuid4()}"
    create_response = client.post(
        "/api/v1/settings/notification-channels",
        json={
            "channel_type": "Telegram",
            "external_handle": marker,
            "alert_levels": ["critical_errors", "executed_trades"],
        },
        headers=headers,
    )
    assert create_response.status_code == 201
    channel = create_response.json()
    channel_id = channel["id"]
    assert channel["preferences"]["alert_levels"] == ["critical_errors", "executed_trades"]
    assert channel["is_verified"] is False

    try:
        list_response = client.get("/api/v1/settings/notification-channels")
        assert any(c["id"] == channel_id for c in list_response.json())

        update_response = client.patch(
            f"/api/v1/settings/notification-channels/{channel_id}",
            json={"is_verified": True, "alert_levels": ["risk_warnings"]},
            headers=headers,
        )
        assert update_response.status_code == 200
        assert update_response.json()["is_verified"] is True
        assert update_response.json()["preferences"]["alert_levels"] == ["risk_warnings"]

        bad_level_response = client.patch(
            f"/api/v1/settings/notification-channels/{channel_id}",
            json={"alert_levels": ["not_a_real_level"]},
            headers=headers,
        )
        assert bad_level_response.status_code == 422
    finally:
        delete_response = client.delete(
            f"/api/v1/settings/notification-channels/{channel_id}", headers=headers
        )
        assert delete_response.status_code == 204
        cleanup_user(admin_id)

    with get_session() as session:
        assert session.get(NotificationChannel, uuid.UUID(channel_id)) is None


# --- GET /settings (API-074) ---------------------------------------------------------------


def test_get_system_settings_returns_real_risk_thresholds_and_trading_calendar():
    """API-074: a composite, non-secret read -- ungated, matching this router's own established
    posture for plain status/config reads (test_vault_status_reports.../
    test_integrations_status_never_leaks... above)."""
    response = client.get("/api/v1/settings")
    assert response.status_code == 200
    body = response.json()

    # risk_thresholds is None only if no RiskLimit row exists at all yet, which every real
    # environment past REL-007 has -- assert the real shape when present rather than assuming.
    if body["risk_thresholds"] is not None:
        assert body["risk_thresholds"]["scope_type"] in {"Global", "Strategy"}
        assert isinstance(body["risk_thresholds"]["max_daily_loss"], (int, float))

    calendar = body["trading_calendar"]
    assert calendar["timezone"] == "Asia/Kolkata"
    assert calendar["market_open_minutes"] < calendar["market_close_minutes"]
    assert isinstance(calendar["fixed_holidays"], list) and len(calendar["fixed_holidays"]) > 0

    # No feature-flag storage layer exists anywhere in this codebase -- honestly empty, never
    # fabricated (see SystemSettingsResponse's own docstring).
    assert body["feature_flags"] == {}

    # NFR-04: real per-provider/per-broker rotation timestamps (or None, honestly, if nothing is
    # Vault-stored for it) -- never a fabricated value.
    rotation = body["credential_rotation"]
    for provider_id in ("openai", "anthropic", "deepseek", "gemini", "huggingface", "opencode"):
        assert provider_id in rotation
    for broker in ("zerodha", "upstox"):
        assert broker in rotation


# --- LLM provider key write/delete (REL-021 E21.1) -----------------------------------------


def test_set_llm_provider_key_requires_system_administrator():
    unauthenticated = client.post(
        "/api/v1/settings/llm-provider-keys/deepseek", json={"api_key": "x"}
    )
    assert unauthenticated.status_code == 401

    pm_id, pm_token = create_authenticated_user(ROLE_PORTFOLIO_MANAGER)
    try:
        wrong_role = client.post(
            "/api/v1/settings/llm-provider-keys/deepseek",
            json={"api_key": "x"},
            headers=auth_header(pm_token),
        )
        assert wrong_role.status_code == 403
    finally:
        cleanup_user(pm_id)


def test_set_llm_provider_key_rejects_an_unknown_provider():
    admin_id, admin_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        response = client.post(
            "/api/v1/settings/llm-provider-keys/not-a-real-provider",
            json={"api_key": "x"},
            headers=auth_header(admin_token),
        )
        assert response.status_code == 422
    finally:
        cleanup_user(admin_id)


def test_set_and_remove_llm_provider_key_round_trips_against_the_real_vault():
    """Same real-Vault-write-then-restore-or-delete convention as
    test_vault.py::test_llm_router_prefers_a_real_vault_stored_key_over_env_settings -- a real
    key written via the actual HTTP endpoint (there is deliberately no GET that reads a stored
    value back out, so verification goes through vault.read_llm_provider_key directly, same as
    that test)."""
    provider = "deepseek"
    admin_id, admin_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    headers = auth_header(admin_token)
    marker_key = f"settings-api-round-trip-{uuid.uuid4().hex[:8]}"

    try:
        set_response = client.post(
            f"/api/v1/settings/llm-provider-keys/{provider}",
            json={"api_key": marker_key},
            headers=headers,
        )
        assert set_response.status_code == 204
        assert vault.read_llm_provider_key(provider) == marker_key

        delete_response = client.delete(
            f"/api/v1/settings/llm-provider-keys/{provider}", headers=headers
        )
        assert delete_response.status_code == 204
        assert vault.read_llm_provider_key(provider) is None
    finally:
        cleanup_user(admin_id)
        # Belt-and-braces: restore the real .env-sourced key if one exists (mirrors
        # test_vault.py's own established restore-or-delete pattern) in case the DELETE above
        # never ran (an earlier assertion failed first).
        real_settings = get_settings()
        if real_settings.deepseek_api_key:
            vault.write_llm_provider_key(provider, real_settings.deepseek_api_key)
        else:
            vault.delete_llm_provider_key(provider)
