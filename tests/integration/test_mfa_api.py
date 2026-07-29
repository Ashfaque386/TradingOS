"""MFA endpoint integration tests (REL-007 E7.1, SEC-014) against the real FastAPI app + real
Postgres + real Vault -- exit criterion 1: "A real MFA challenge blocks login for the three
mandated roles without a valid TOTP code."
"""

import uuid

import pyotp
from fastapi.testclient import TestClient

from src.api.main import app
from src.core import vault
from src.core.db import get_session
from src.core.security import (
    ROLE_READ_ONLY_AUDITOR,
    ROLE_RISK_MANAGER,
    ROLE_SYSTEM_ADMINISTRATOR,
    create_mfa_pending_token,
    hash_password,
)
from src.models.user import MfaBackupCode, User
from tests.auth_helpers import auth_header, cleanup_user, create_authenticated_user

client = TestClient(app)


def _create_mandatory_role_user(role: str, *, mfa_enabled: bool = False) -> tuple[uuid.UUID, str]:
    """Returns (user_id, pending_token) -- a mandatory-role user with a real pending-MFA token,
    the state /login would put them in after a correct password."""
    user_id = uuid.uuid4()
    with get_session() as session:
        session.add(
            User(
                id=user_id,
                email=f"mfa-test-{user_id}@example.invalid",
                hashed_password=hash_password("test-password-123"),
                role=role,
                mfa_enabled=mfa_enabled,
            )
        )
        session.commit()
    pending_token = create_mfa_pending_token(user_id=str(user_id), role=role)
    return user_id, pending_token


def test_read_only_auditor_login_is_unaffected_by_mfa():
    user_id, token = create_authenticated_user(ROLE_READ_ONLY_AUDITOR)
    try:
        # create_authenticated_user mints a token directly, bypassing /login -- confirm the real
        # login path for this non-mandatory role separately.
        with get_session() as session:
            user = session.get(User, user_id)
            assert user is not None
            email = user.email
        response = client.post(
            "/api/v1/auth/login", json={"email": email, "password": "test-password-123"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["mfa_required"] is False
        assert body["access_token"] is not None
        me = client.get("/api/v1/auth/me", headers=auth_header(body["access_token"]))
        assert me.status_code == 200
    finally:
        cleanup_user(user_id)
        vault.delete_mfa_secret(str(user_id))


def test_enroll_confirm_round_trip_with_a_real_totp_code():
    user_id, pending_token = _create_mandatory_role_user(ROLE_SYSTEM_ADMINISTRATOR)
    headers = auth_header(pending_token)
    try:
        enroll = client.post("/api/v1/auth/mfa/enroll", headers=headers)
        assert enroll.status_code == 200
        body = enroll.json()
        assert len(body["backup_codes"]) == 10
        secret = body["secret_base32"]

        confirm = client.post(
            "/api/v1/auth/mfa/confirm",
            json={"totp_code": pyotp.TOTP(secret).now()},
            headers=headers,
        )
        assert confirm.status_code == 200
        access_token = confirm.json()["access_token"]

        with get_session() as session:
            user = session.get(User, user_id)
            assert user is not None
            assert user.mfa_enabled is True

        me = client.get("/api/v1/auth/me", headers=auth_header(access_token))
        assert me.status_code == 200
    finally:
        cleanup_user(user_id)
        vault.delete_mfa_secret(str(user_id))


def test_subsequent_login_verifies_via_a_fresh_real_totp_code():
    secret = pyotp.random_base32()
    user_id, pending_token = _create_mandatory_role_user(ROLE_RISK_MANAGER, mfa_enabled=True)
    vault.write_mfa_secret(str(user_id), secret)
    try:
        verify = client.post(
            "/api/v1/auth/mfa/verify",
            json={"totp_code": pyotp.TOTP(secret).now()},
            headers=auth_header(pending_token),
        )
        assert verify.status_code == 200
        access_token = verify.json()["access_token"]
        me = client.get("/api/v1/auth/me", headers=auth_header(access_token))
        assert me.status_code == 200
    finally:
        cleanup_user(user_id)
        vault.delete_mfa_secret(str(user_id))


def test_wrong_totp_code_is_rejected():
    secret = pyotp.random_base32()
    user_id, pending_token = _create_mandatory_role_user(ROLE_RISK_MANAGER, mfa_enabled=True)
    vault.write_mfa_secret(str(user_id), secret)
    try:
        response = client.post(
            "/api/v1/auth/mfa/verify",
            json={"totp_code": "000000"},
            headers=auth_header(pending_token),
        )
        assert response.status_code == 401
    finally:
        cleanup_user(user_id)
        vault.delete_mfa_secret(str(user_id))


def test_backup_code_works_once_and_then_fails():
    user_id, pending_token = _create_mandatory_role_user(ROLE_SYSTEM_ADMINISTRATOR)
    headers = auth_header(pending_token)
    try:
        enroll = client.post("/api/v1/auth/mfa/enroll", headers=headers)
        secret = enroll.json()["secret_base32"]
        backup_code = enroll.json()["backup_codes"][0]
        client.post(
            "/api/v1/auth/mfa/confirm",
            json={"totp_code": pyotp.TOTP(secret).now()},
            headers=headers,
        )

        # Fresh pending token, as a real subsequent login would issue.
        second_pending = create_mfa_pending_token(
            user_id=str(user_id), role=ROLE_SYSTEM_ADMINISTRATOR
        )
        first_use = client.post(
            "/api/v1/auth/mfa/verify",
            json={"backup_code": backup_code},
            headers=auth_header(second_pending),
        )
        assert first_use.status_code == 200

        third_pending = create_mfa_pending_token(
            user_id=str(user_id), role=ROLE_SYSTEM_ADMINISTRATOR
        )
        reuse = client.post(
            "/api/v1/auth/mfa/verify",
            json={"backup_code": backup_code},
            headers=auth_header(third_pending),
        )
        assert reuse.status_code == 401
    finally:
        cleanup_user(user_id)
        vault.delete_mfa_secret(str(user_id))


def test_admin_disable_resets_another_users_mfa():
    admin_id, admin_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    target_id, pending_token = _create_mandatory_role_user(ROLE_RISK_MANAGER, mfa_enabled=True)
    vault.write_mfa_secret(str(target_id), pyotp.random_base32())
    try:
        with get_session() as session:
            session.add(MfaBackupCode(user_id=target_id, code_hash="irrelevant-hash"))
            session.commit()

        response = client.post(
            "/api/v1/auth/mfa/disable",
            json={"user_id": str(target_id)},
            headers=auth_header(admin_token),
        )
        assert response.status_code == 200

        with get_session() as session:
            target = session.get(User, target_id)
            assert target is not None
            assert target.mfa_enabled is False
            remaining_codes = (
                session.query(MfaBackupCode).filter(MfaBackupCode.user_id == target_id).count()
            )
            assert remaining_codes == 0

        assert vault.read_mfa_secret(str(target_id)) is None
    finally:
        cleanup_user(admin_id)
        cleanup_user(target_id)
        vault.delete_mfa_secret(str(target_id))


def test_mfa_verify_fails_closed_when_vault_has_no_secret_for_an_enrolled_user():
    # mfa_enabled=True but nothing was ever written to Vault for this user -- simulates a Vault
    # wipe. Must 503, never silently pass the check.
    user_id, pending_token = _create_mandatory_role_user(ROLE_RISK_MANAGER, mfa_enabled=True)
    try:
        response = client.post(
            "/api/v1/auth/mfa/verify",
            json={"totp_code": "123456"},
            headers=auth_header(pending_token),
        )
        assert response.status_code == 503
    finally:
        cleanup_user(user_id)
