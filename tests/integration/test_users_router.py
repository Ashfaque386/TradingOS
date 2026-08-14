"""User management API integration test (src/api/routers/users.py) against the real FastAPI app
+ real Postgres. Covers the two rows added this pass -- API-004 (PATCH .../role) and API-005
(DELETE, a soft deactivation) -- plus the router-level SystemAdministrator-only gate every route
here already shares.
"""

import uuid

from fastapi.testclient import TestClient

from src.api.main import app
from src.core.db import get_session
from src.core.security import (
    ROLE_PORTFOLIO_MANAGER,
    ROLE_READ_ONLY_AUDITOR,
    ROLE_SYSTEM_ADMINISTRATOR,
)
from src.models.user import User
from tests.auth_helpers import auth_header, cleanup_user, create_authenticated_user

client = TestClient(app)


def _create_target_user() -> uuid.UUID:
    user_id, _ = create_authenticated_user(ROLE_PORTFOLIO_MANAGER)
    return user_id


def test_role_and_deactivation_mutations_require_system_administrator():
    non_admin_id, non_admin_token = create_authenticated_user(ROLE_READ_ONLY_AUDITOR)
    target_id = _create_target_user()
    try:
        role_response = client.patch(
            f"/api/v1/users/{target_id}/role",
            json={"role": ROLE_SYSTEM_ADMINISTRATOR},
            headers=auth_header(non_admin_token),
        )
        assert role_response.status_code == 403

        delete_response = client.delete(
            f"/api/v1/users/{target_id}", headers=auth_header(non_admin_token)
        )
        assert delete_response.status_code == 403
    finally:
        cleanup_user(non_admin_id)
        cleanup_user(target_id)


def test_update_user_role_changes_the_real_row():
    admin_id, admin_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    target_id = _create_target_user()
    try:
        response = client.patch(
            f"/api/v1/users/{target_id}/role",
            json={"role": "RiskManager"},
            headers=auth_header(admin_token),
        )
        assert response.status_code == 200
        assert response.json()["role"] == "RiskManager"

        with get_session() as session:
            row = session.get(User, target_id)
            assert row is not None
            assert row.role == "RiskManager"
    finally:
        cleanup_user(admin_id)
        cleanup_user(target_id)


def test_update_user_role_rejects_an_unknown_role():
    admin_id, admin_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    target_id = _create_target_user()
    try:
        response = client.patch(
            f"/api/v1/users/{target_id}/role",
            json={"role": "NotARealRole"},
            headers=auth_header(admin_token),
        )
        assert response.status_code == 422
    finally:
        cleanup_user(admin_id)
        cleanup_user(target_id)


def test_update_user_role_404s_for_an_unknown_user():
    admin_id, admin_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        response = client.patch(
            f"/api/v1/users/{uuid.uuid4()}/role",
            json={"role": ROLE_SYSTEM_ADMINISTRATOR},
            headers=auth_header(admin_token),
        )
        assert response.status_code == 404
    finally:
        cleanup_user(admin_id)


def test_deactivate_user_soft_deactivates_never_deletes_the_row():
    admin_id, admin_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    target_id = _create_target_user()
    try:
        response = client.delete(f"/api/v1/users/{target_id}", headers=auth_header(admin_token))
        assert response.status_code == 200
        body = response.json()
        assert body["is_active"] is False

        with get_session() as session:
            row = session.get(User, target_id)
            assert row is not None, "deactivate must never hard-delete the row"
            assert row.is_active is False
    finally:
        cleanup_user(admin_id)
        cleanup_user(target_id)


def test_deactivate_user_404s_for_an_unknown_user():
    admin_id, admin_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        response = client.delete(f"/api/v1/users/{uuid.uuid4()}", headers=auth_header(admin_token))
        assert response.status_code == 404
    finally:
        cleanup_user(admin_id)
