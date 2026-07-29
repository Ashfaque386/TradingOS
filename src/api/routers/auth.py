"""Login endpoint (Phase 4 exit-criteria gap). See src/core/security.py's module docstring for
what this real-but-reduced auth layer covers relative to the full Phase_12 design.
"""

import hashlib
import ipaddress
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import func, select, update

from src.api.deps import get_current_user
from src.core.audit import write_audit_entry
from src.core.db import get_session
from src.core.security import (
    MFA_MANDATORY_ROLES,
    create_access_token,
    create_mfa_pending_token,
    verify_password,
)
from src.core.session import REFRESH_TOKEN_TTL_DAYS, issue_session
from src.core.vault_transit import VaultTransitUnavailableError
from src.models.refresh_token import RefreshToken
from src.models.user import User

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    # REL-007 E7.1: a mandatory-MFA-role user (src/core/security.py::MFA_MANDATORY_ROLES) never
    # gets access_token/refresh_token here -- only pending_token, to be exchanged at
    # POST /api/v1/auth/mfa/{confirm,verify}. mfa_required=False is the unaffected, unchanged
    # path every pre-existing non-mandatory-role test and caller already exercises.
    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str = "bearer"
    user_id: uuid.UUID
    role: str
    mfa_required: bool = False
    mfa_enrolled: bool = False
    pending_token: str | None = None


def _valid_client_ip(request: Request) -> str | None:
    """AuditLog.ip_address is a real Postgres INET column -- ASGI's `request.client.host` isn't
    guaranteed to be a parseable IP (FastAPI's own TestClient sets it to the literal string
    "testclient", not an address; a misconfigured reverse proxy could set an arbitrary
    Host-header-derived value too). Validate before ever handing it to the DB rather than let a
    non-IP value 500 the login endpoint -- found via a real TestClient-driven integration test
    failure, not a hypothetical."""
    if request.client is None:
        return None
    try:
        ipaddress.ip_address(request.client.host)
    except ValueError:
        return None
    return request.client.host


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request) -> LoginResponse:
    client_ip = _valid_client_ip(request)

    with get_session() as session:
        user = session.scalars(select(User).where(User.email == body.email)).first()
        # Constant-shape response whether the email doesn't exist or the password is wrong --
        # never reveal which one via a different error, since that lets an attacker enumerate
        # valid emails.
        if user is None or not verify_password(body.password, user.hashed_password):
            # Keyed on the attempted email, not a resolved user_id, since the credential is
            # wrong (or the account doesn't exist) -- a real detective control for
            # credential-stuffing/brute-force per SEC-010's threat model.
            write_audit_entry(
                session,
                actor_type="Human",
                actor_id=body.email,
                action="LOGIN_FAILURE",
                entity_type="User",
                ip_address=client_ip,
            )
            session.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password"
            )
        if not user.is_active:
            write_audit_entry(
                session,
                actor_type="Human",
                actor_id=user.email,
                action="LOGIN_FAILURE",
                entity_type="User",
                entity_id=user.id,
                ip_address=client_ip,
            )
            session.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Account is inactive"
            )

        # Use the DB's own clock (func.now()) rather than Python's, and update via a targeted
        # statement instead of mutating the detached-after-commit ORM object.
        session.execute(update(User).where(User.id == user.id).values(last_login_at=func.now()))
        write_audit_entry(
            session,
            actor_type="Human",
            actor_id=user.email,
            action="LOGIN_SUCCESS",
            entity_type="User",
            entity_id=user.id,
            ip_address=client_ip,
        )
        session.commit()

        try:
            if user.role in MFA_MANDATORY_ROLES:
                # REL-007 E7.1: password was correct, but a mandatory-role user never gets a
                # real access token from /login directly -- only a short-lived pending token,
                # exchanged for a real session at /mfa/confirm (first-time enrollment) or
                # /mfa/verify (already enrolled). 200, not 401/403: the credential itself was
                # right.
                pending_token = create_mfa_pending_token(user_id=str(user.id), role=user.role)
                return LoginResponse(
                    user_id=user.id,
                    role=user.role,
                    mfa_required=True,
                    mfa_enrolled=user.mfa_enabled,
                    pending_token=pending_token,
                )
            issued = issue_session(session, user)
            session.commit()
        except VaultTransitUnavailableError as exc:
            # Fail closed (REL-007 E7.2): a password was verified but Vault Transit can't sign a
            # token for it. Never fall back to an insecure signing scheme -- surface the outage
            # loudly instead.
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication is temporarily unavailable",
            ) from exc
        return LoginResponse(
            access_token=issued.access_token,
            refresh_token=issued.refresh_token,
            user_id=user.id,
            role=user.role,
        )


def _hash_refresh_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


@router.post("/refresh", response_model=RefreshResponse)
def refresh(body: RefreshRequest) -> RefreshResponse:
    """REL-007 E7.3 (SEC-012): no bearer auth required -- the refresh token itself is the
    credential. Single-use: a real re-presentation of an already-used or already-revoked token
    revokes the entire rotation family, not just the reused row (theft detection -- see
    src/models/refresh_token.py's docstring for why that's the correct response, not just
    rejecting the one reused token)."""
    token_hash = _hash_refresh_token(body.refresh_token)
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
    )

    with get_session() as session:
        row = session.scalars(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        ).first()
        if row is None:
            raise invalid

        if row.used_at is not None or row.revoked_at is not None:
            now = datetime.now(UTC)
            session.execute(
                update(RefreshToken)
                .where(RefreshToken.family_id == row.family_id, RefreshToken.revoked_at.is_(None))
                .values(revoked_at=now, revoked_reason="REUSE_DETECTED")
            )
            write_audit_entry(
                session,
                actor_type="System",
                actor_id=str(row.user_id),
                action="REFRESH_TOKEN_REUSE_DETECTED",
                entity_type="User",
                entity_id=row.user_id,
                after_state={"family_id": str(row.family_id)},
            )
            session.commit()
            raise invalid

        if row.expires_at < datetime.now(UTC):
            raise invalid

        user = session.get(User, row.user_id)
        if user is None or not user.is_active:
            raise invalid

        row.used_at = datetime.now(UTC)

        new_access_token = create_access_token(user_id=str(user.id), role=user.role)
        raw_new_refresh_token = secrets.token_urlsafe(32)
        session.add(
            RefreshToken(
                user_id=user.id,
                token_hash=_hash_refresh_token(raw_new_refresh_token),
                family_id=row.family_id,
                parent_id=row.id,
                expires_at=datetime.now(UTC) + timedelta(days=REFRESH_TOKEN_TTL_DAYS),
            )
        )
        session.commit()

    return RefreshResponse(access_token=new_access_token, refresh_token=raw_new_refresh_token)


class LogoutRequest(BaseModel):
    refresh_token: str


class LogoutResponse(BaseModel):
    status: str


@router.post("/logout", response_model=LogoutResponse)
def logout(body: LogoutRequest, _user: User = Depends(get_current_user)) -> LogoutResponse:
    token_hash = _hash_refresh_token(body.refresh_token)
    with get_session() as session:
        session.execute(
            update(RefreshToken)
            .where(RefreshToken.token_hash == token_hash, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC), revoked_reason="LOGOUT")
        )
        session.commit()
    return LogoutResponse(status="LOGGED_OUT")


class CurrentUserResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str | None
    role: str


@router.get("/me", response_model=CurrentUserResponse)
def me(user: User = Depends(get_current_user)) -> CurrentUserResponse:
    return CurrentUserResponse(
        id=user.id, email=user.email, full_name=user.full_name, role=user.role
    )
