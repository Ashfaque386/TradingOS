"""Auth API integration test (Phase 4 exit-criteria gap): src/api/routers/auth.py and
src/api/routers/users.py against the real FastAPI app + real Postgres. Also proves the
require_role dependency actually blocks the wrong role on a real protected endpoint
(POST /system/kill-switch), not just in isolation.
"""

import uuid

from fastapi.testclient import TestClient

from src.api.main import app
from src.core.db import get_session
from src.core.security import (
    ROLE_PORTFOLIO_MANAGER,
    ROLE_READ_ONLY_AUDITOR,
    ROLE_SYSTEM_ADMINISTRATOR,
    hash_password,
)
from src.models.user import User
from tests.auth_helpers import auth_header, cleanup_user, create_authenticated_user

client = TestClient(app)


def test_login_with_correct_credentials_returns_a_real_usable_token():
    # MFA enforcement is currently disabled for every role (src/core/security.py::
    # MFA_MANDATORY_ROLES, turned off 2026-07-28 per explicit user request -- the real
    # enroll/confirm/verify machinery is untouched and still separately tested in
    # tests/integration/test_mfa_api.py). While disabled, login returns a real usable token
    # directly for every role, same as REL-004's original baseline behavior.
    email = f"login-test-{uuid.uuid4()}@example.invalid"
    password = "a-real-password-123"
    user_id = uuid.uuid4()
    with get_session() as session:
        session.add(
            User(
                id=user_id,
                email=email,
                hashed_password=hash_password(password),
                role=ROLE_SYSTEM_ADMINISTRATOR,
            )
        )
        session.commit()

    try:
        response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert response.status_code == 200
        body = response.json()
        assert body["role"] == ROLE_SYSTEM_ADMINISTRATOR
        assert body["user_id"] == str(user_id)
        assert body["mfa_required"] is False
        assert body["access_token"] is not None

        me_response = client.get("/api/v1/auth/me", headers=auth_header(body["access_token"]))
        assert me_response.status_code == 200
        assert me_response.json()["email"] == email
    finally:
        cleanup_user(user_id)


def test_login_with_wrong_password_is_rejected_without_revealing_which_field_was_wrong():
    email = f"login-test-{uuid.uuid4()}@example.invalid"
    user_id = uuid.uuid4()
    with get_session() as session:
        session.add(
            User(
                id=user_id,
                email=email,
                hashed_password=hash_password("the-real-password"),
                role=ROLE_READ_ONLY_AUDITOR,
            )
        )
        session.commit()

    try:
        wrong_password = client.post(
            "/api/v1/auth/login", json={"email": email, "password": "not-the-real-password"}
        )
        unknown_email = client.post(
            "/api/v1/auth/login", json={"email": "nobody@example.invalid", "password": "anything"}
        )
        assert wrong_password.status_code == 401
        assert unknown_email.status_code == 401
        assert wrong_password.json()["detail"] == unknown_email.json()["detail"]
    finally:
        cleanup_user(user_id)


def test_a_protected_endpoint_rejects_no_token_and_the_wrong_role_but_accepts_the_right_one():
    _, auditor_token = create_authenticated_user(ROLE_READ_ONLY_AUDITOR)
    admin_id, admin_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)

    try:
        no_token = client.post("/api/v1/system/kill-switch/reset", json={"confirmation": False})
        wrong_role = client.post(
            "/api/v1/system/kill-switch/reset",
            json={"confirmation": False},
            headers=auth_header(auditor_token),
        )
        # confirmation=False so a successful auth check still 400s rather than actually
        # resetting -- this test is only about the 401/403/passes-through boundary.
        right_role = client.post(
            "/api/v1/system/kill-switch/reset",
            json={"confirmation": False},
            headers=auth_header(admin_token),
        )

        assert no_token.status_code == 401
        assert wrong_role.status_code == 403
        assert right_role.status_code == 400  # past the role gate, rejected by confirmation=False
    finally:
        cleanup_user(admin_id)


def test_users_endpoint_is_system_administrator_only():
    _, pm_token = create_authenticated_user(ROLE_PORTFOLIO_MANAGER)
    admin_id, admin_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)

    try:
        as_pm = client.get("/api/v1/users", headers=auth_header(pm_token))
        as_admin = client.get("/api/v1/users", headers=auth_header(admin_token))

        assert as_pm.status_code == 403
        assert as_admin.status_code == 200
        assert any(u["id"] == str(admin_id) for u in as_admin.json())
    finally:
        cleanup_user(admin_id)


def test_admin_can_create_a_new_user_with_a_hashed_password_never_returned():
    admin_id, admin_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    new_email = f"created-by-admin-{uuid.uuid4()}@example.invalid"
    created_user_id = None

    try:
        response = client.post(
            "/api/v1/users",
            json={
                "email": new_email,
                "password": "a-new-password-123",
                "role": ROLE_PORTFOLIO_MANAGER,
            },
            headers=auth_header(admin_token),
        )
        assert response.status_code == 201
        body = response.json()
        created_user_id = uuid.UUID(body["id"])
        assert body["email"] == new_email
        assert body["role"] == ROLE_PORTFOLIO_MANAGER
        assert "password" not in body
        assert "hashed_password" not in body

        login = client.post(
            "/api/v1/auth/login", json={"email": new_email, "password": "a-new-password-123"}
        )
        assert login.status_code == 200
    finally:
        cleanup_user(admin_id)
        if created_user_id is not None:
            cleanup_user(created_user_id)
