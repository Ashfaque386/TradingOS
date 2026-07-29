"""MFA enrollment and challenge endpoints (REL-007 E7.1, SEC-014): TOTP second factor, mandatory
for SystemAdministrator/PortfolioManager/RiskManager (src/core/security.py::MFA_MANDATORY_ROLES),
optional for everyone else. See src/api/routers/auth.py's login() for where the pending-MFA
branch begins.

TOTP secrets live in Vault KV (src/core/vault.py::write_mfa_secret, mirroring the existing
broker-credentials/LLM-key pattern), never in Postgres. Backup codes are the opposite: bcrypt-
hashed in Postgres (src/models/user.py::MfaBackupCode), since they need to survive a Vault wipe
as a real recovery path -- see src/core/vault_transit.py's module docstring for the same
Vault-wipe consequence on JWT signing, which applies identically here.

Fail-CLOSED: if a user has mfa_enabled=True but Vault has nothing stored for them (unreachable,
or wiped), /mfa/verify returns 503, never silently skips the check.
"""

import secrets
from datetime import UTC, datetime

import bcrypt
import pyotp
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator
from sqlalchemy import select

from src.api.deps import get_mfa_pending_user, get_user_any_token, require_role
from src.core import vault
from src.core.audit import write_audit_entry
from src.core.db import get_session
from src.core.security import ROLE_SYSTEM_ADMINISTRATOR
from src.core.session import issue_session
from src.models.user import MfaBackupCode, User

router = APIRouter(prefix="/api/v1/auth/mfa", tags=["mfa"])
_can_disable_mfa = require_role(ROLE_SYSTEM_ADMINISTRATOR)

_ISSUER_NAME = "TradingOS"
_BACKUP_CODE_COUNT = 10


def _generate_backup_codes() -> list[str]:
    return [secrets.token_hex(5) for _ in range(_BACKUP_CODE_COUNT)]


class EnrollResponse(BaseModel):
    secret_base32: str
    otpauth_uri: str
    backup_codes: list[str]


@router.post("/enroll", response_model=EnrollResponse)
def enroll(user: User = Depends(get_user_any_token)) -> EnrollResponse:
    """Generates a new TOTP secret + 10 backup codes, returned exactly once in the clear (same
    one-time-reveal convention as an API key -- neither is ever retrievable again after this
    response). Re-enrolling immediately supersedes any previously-enrolled secret in Vault, even
    before /confirm -- deliberate, matches common real-world TOTP re-enrollment behavior, not
    tracked as a separate "pending vs confirmed" state to avoid over-building this."""
    secret = pyotp.random_base32()
    if not vault.write_mfa_secret(str(user.id), secret):
        raise HTTPException(status_code=503, detail="Could not write MFA secret to Vault")

    backup_codes = _generate_backup_codes()
    with get_session() as session:
        session.query(MfaBackupCode).filter(MfaBackupCode.user_id == user.id).delete()
        for code in backup_codes:
            hashed = bcrypt.hashpw(code.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
            session.add(MfaBackupCode(user_id=user.id, code_hash=hashed))
        session.commit()

    otpauth_uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=_ISSUER_NAME)
    return EnrollResponse(secret_base32=secret, otpauth_uri=otpauth_uri, backup_codes=backup_codes)


class ConfirmRequest(BaseModel):
    totp_code: str


class SessionResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: str
    role: str


@router.post("/confirm", response_model=SessionResponse)
def confirm(body: ConfirmRequest, user: User = Depends(get_user_any_token)) -> SessionResponse:
    """Finalizes enrollment: a correct TOTP code against the just-enrolled secret flips
    mfa_enabled and issues a real session -- this is what upgrades a pending-MFA login into a
    usable one."""
    secret = vault.read_mfa_secret(str(user.id))
    if secret is None:
        raise HTTPException(status_code=503, detail="MFA secret unavailable -- enroll again")
    if not pyotp.TOTP(secret).verify(body.totp_code, valid_window=1):
        raise HTTPException(status_code=401, detail="Incorrect TOTP code")

    with get_session() as session:
        session.query(User).filter(User.id == user.id).update({"mfa_enabled": True})
        write_audit_entry(
            session,
            actor_type="Human",
            actor_id=user.email,
            action="MFA_ENROLLED",
            entity_type="User",
            entity_id=user.id,
        )
        issued = issue_session(session, user)
        session.commit()

    return SessionResponse(
        access_token=issued.access_token,
        refresh_token=issued.refresh_token,
        user_id=str(user.id),
        role=user.role,
    )


class VerifyRequest(BaseModel):
    totp_code: str | None = None
    backup_code: str | None = None

    @model_validator(mode="after")
    def _exactly_one_factor(self) -> "VerifyRequest":
        if bool(self.totp_code) == bool(self.backup_code):
            raise ValueError("provide exactly one of totp_code or backup_code")
        return self


def _verify_backup_code(session, user_id, backup_code: str) -> bool:  # type: ignore[no-untyped-def]
    unused_codes = session.scalars(
        select(MfaBackupCode).where(
            MfaBackupCode.user_id == user_id, MfaBackupCode.used_at.is_(None)
        )
    )
    for row in unused_codes:
        if bcrypt.checkpw(backup_code.encode("utf-8"), row.code_hash.encode("utf-8")):
            row.used_at = datetime.now(UTC)
            return True
    return False


@router.post("/verify", response_model=SessionResponse)
def verify(body: VerifyRequest, user: User = Depends(get_mfa_pending_user)) -> SessionResponse:
    """For already-enrolled users on subsequent logins -- reached only via the pending-MFA token
    src/api/routers/auth.py's login() issues for a mandatory-role user."""
    with get_session() as session:
        ok = False
        if body.totp_code is not None:
            secret = vault.read_mfa_secret(str(user.id))
            if secret is None:
                raise HTTPException(status_code=503, detail="MFA verification unavailable")
            ok = pyotp.TOTP(secret).verify(body.totp_code, valid_window=1)
        else:
            assert body.backup_code is not None
            ok = _verify_backup_code(session, user.id, body.backup_code)

        write_audit_entry(
            session,
            actor_type="Human",
            actor_id=user.email,
            action="MFA_LOGIN_SUCCESS" if ok else "MFA_LOGIN_FAILURE",
            entity_type="User",
            entity_id=user.id,
        )
        if not ok:
            session.commit()
            raise HTTPException(status_code=401, detail="Incorrect MFA code")

        issued = issue_session(session, user)
        session.commit()

    return SessionResponse(
        access_token=issued.access_token,
        refresh_token=issued.refresh_token,
        user_id=str(user.id),
        role=user.role,
    )


class DisableRequest(BaseModel):
    user_id: str


class DisableResponse(BaseModel):
    status: str


@router.post("/disable", response_model=DisableResponse)
def disable(body: DisableRequest, _admin: User = Depends(_can_disable_mfa)) -> DisableResponse:
    """Admin recovery path: resets a user locked out by a Vault wipe (their TOTP secret is gone
    and unrecoverable) or by losing both their authenticator and their backup codes."""
    with get_session() as session:
        target = session.get(User, body.user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="User not found")
        target.mfa_enabled = False
        session.query(MfaBackupCode).filter(MfaBackupCode.user_id == target.id).delete()
        vault.delete_mfa_secret(str(target.id))
        write_audit_entry(
            session,
            actor_type="Human",
            actor_id=_admin.email,
            action="MFA_RESET_BY_ADMIN",
            entity_type="User",
            entity_id=target.id,
        )
        session.commit()
    return DisableResponse(status="MFA_DISABLED")
