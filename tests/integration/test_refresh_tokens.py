"""Refresh-token rotation integration tests (REL-007 E7.3, SEC-012) against the real FastAPI app
+ real Postgres -- exit criterion 3: "A stolen/replayed refresh token is detected and revokes
the session family (real test, not just a unit assertion on the revocation function)."
"""

import uuid

from fastapi.testclient import TestClient

from src.api.main import app
from src.core.db import get_session
from src.core.security import ROLE_READ_ONLY_AUDITOR, ROLE_SYSTEM_ADMINISTRATOR, hash_password
from src.models.user import User
from tests.auth_helpers import auth_header, cleanup_user, create_authenticated_user

client = TestClient(app)


def _create_login_ready_user() -> tuple[uuid.UUID, str, str]:
    """Returns (user_id, email, password) for a non-MFA-mandatory role -- ReadOnlyAuditor logs
    in directly via POST /login with no MFA challenge in the way."""
    user_id = uuid.uuid4()
    email = f"refresh-test-{user_id}@example.invalid"
    password = "test-password-123"
    with get_session() as session:
        session.add(
            User(
                id=user_id,
                email=email,
                hashed_password=hash_password(password),
                role=ROLE_READ_ONLY_AUDITOR,
            )
        )
        session.commit()
    return user_id, email, password


def test_login_returns_both_tokens_and_refresh_round_trips_to_a_fresh_usable_pair():
    user_id, email, password = _create_login_ready_user()
    try:
        login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert login.status_code == 200
        body = login.json()
        assert body["access_token"] is not None
        assert body["refresh_token"] is not None

        refreshed = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]}
        )
        assert refreshed.status_code == 200
        new_body = refreshed.json()
        assert new_body["access_token"] != body["access_token"]
        assert new_body["refresh_token"] != body["refresh_token"]

        me = client.get("/api/v1/auth/me", headers=auth_header(new_body["access_token"]))
        assert me.status_code == 200
    finally:
        cleanup_user(user_id)


def test_reusing_an_already_rotated_refresh_token_revokes_the_whole_family():
    user_id, email, password = _create_login_ready_user()
    try:
        login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
        original_refresh_token = login.json()["refresh_token"]

        first_refresh = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": original_refresh_token}
        )
        assert first_refresh.status_code == 200
        rotated_refresh_token = first_refresh.json()["refresh_token"]

        # Real theft simulation: replay the already-used original token.
        replay = client.post("/api/v1/auth/refresh", json={"refresh_token": original_refresh_token})
        assert replay.status_code == 401

        # The legitimate rotation's own successor is now ALSO revoked -- the whole family died,
        # not just the reused token. This is the actual theft-detection behavior under test.
        legitimate_next_refresh = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": rotated_refresh_token}
        )
        assert legitimate_next_refresh.status_code == 401
    finally:
        cleanup_user(user_id)


def test_an_unknown_refresh_token_is_rejected():
    response = client.post("/api/v1/auth/refresh", json={"refresh_token": "not-a-real-token"})
    assert response.status_code == 401


def test_logout_revokes_the_refresh_token():
    user_id, email, password = _create_login_ready_user()
    try:
        login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
        body = login.json()

        logout = client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": body["refresh_token"]},
            headers=auth_header(body["access_token"]),
        )
        assert logout.status_code == 200

        refresh_after_logout = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]}
        )
        assert refresh_after_logout.status_code == 401
    finally:
        cleanup_user(user_id)


def test_admin_can_revoke_every_session_for_a_user():
    sa_id, sa_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    target_id, email, password = _create_login_ready_user()
    try:
        login_a = client.post("/api/v1/auth/login", json={"email": email, "password": password})
        login_b = client.post("/api/v1/auth/login", json={"email": email, "password": password})
        refresh_token_a = login_a.json()["refresh_token"]
        refresh_token_b = login_b.json()["refresh_token"]

        response = client.post(
            f"/api/v1/users/{target_id}/revoke-sessions", headers=auth_header(sa_token)
        )
        assert response.status_code == 200
        assert response.json()["revoked_count"] >= 2

        assert (
            client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token_a}).status_code
            == 401
        )
        assert (
            client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token_b}).status_code
            == 401
        )
    finally:
        cleanup_user(sa_id)
        cleanup_user(target_id)
