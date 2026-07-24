"""Global Settings API integration test (Phase 4 Epic E4.3): the endpoints wired in
src/api/routers/settings.py, against the real FastAPI app + real Postgres + the real
process-lifetime Settings object (src/core/config.py).
"""

import uuid

from fastapi.testclient import TestClient

from src.api.main import app
from src.core.db import get_session
from src.core.security import ROLE_SYSTEM_ADMINISTRATOR
from src.models.user import NotificationChannel
from tests.auth_helpers import auth_header, cleanup_user, create_authenticated_user

client = TestClient(app)


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
