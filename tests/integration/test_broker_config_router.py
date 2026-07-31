"""REL-010 E10.8b: broker configuration & read endpoints (src/api/routers/broker_config.py)
against the real FastAPI app + real Postgres + real dev Vault.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.core import vault
from src.core.security import ROLE_READ_ONLY_AUDITOR, ROLE_SYSTEM_ADMINISTRATOR
from tests.auth_helpers import auth_header, cleanup_user, create_authenticated_user

client = TestClient(app)


def test_broker_status_reflects_real_configuration_state():
    response = client.get("/api/v1/broker/status")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["configured"], bool)
    if not body["configured"]:
        assert body["detail"] is not None


def test_set_credentials_requires_system_administrator_role():
    user_id, token = create_authenticated_user(ROLE_READ_ONLY_AUDITOR)
    try:
        response = client.post(
            "/api/v1/broker/credentials/test-broker",
            json={"credentials": {"api_key": "x"}},
            headers=auth_header(token),
        )
        assert response.status_code == 403
    finally:
        cleanup_user(user_id)


def test_unauthenticated_set_credentials_is_rejected():
    response = client.post(
        "/api/v1/broker/credentials/test-broker", json={"credentials": {"api_key": "x"}}
    )
    assert response.status_code == 401


def test_system_administrator_can_write_and_delete_a_real_vault_credential():
    user_id, token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    broker_name = "e10-8-test-broker"
    try:
        response = client.post(
            f"/api/v1/broker/credentials/{broker_name}",
            json={"credentials": {"api_key": "test-key-value"}},
            headers=auth_header(token),
        )
        if response.status_code == 503:
            pytest.skip("Dev Vault unreachable in this environment")
        assert response.status_code == 204

        stored = vault.read_broker_credentials(broker_name)
        assert stored == {"api_key": "test-key-value"}

        delete_response = client.delete(
            f"/api/v1/broker/credentials/{broker_name}", headers=auth_header(token)
        )
        assert delete_response.status_code == 204
        assert vault.read_broker_credentials(broker_name) is None
    finally:
        vault.delete_broker_credentials(broker_name)
        cleanup_user(user_id)


def test_no_order_placement_path_exists_anywhere_in_this_router():
    """Real, static proof of Business Rule 3 by absence, matching the discipline
    tests/integration/test_portfolio_allocation_recommendation_api.py already applies to the
    portfolio router."""
    source = Path("src/api/routers/broker_config.py").read_text(encoding="utf-8")
    assert "place_order" not in source
    assert "modify_order" not in source
    assert "cancel_order" not in source
