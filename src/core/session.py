"""Session issuance, shared by every path that ends in a real logged-in session: normal
non-MFA-role login (src/api/routers/auth.py) and the MFA enroll/verify endpoints
(src/api/routers/mfa.py) once a challenge is satisfied. One seam, not duplicated per caller.

REL-007 E7.3: also mints and persists a real refresh token (src/models/refresh_token.py) per
session, starting a fresh rotation family. Takes an existing Session (mirrors
src/core/audit.py::write_audit_entry's style) so the caller controls the commit -- issuing a
session is typically the last thing a request does alongside its own state changes (e.g.
updating last_login_at), and both should commit together.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from src.core.security import create_access_token
from src.models.refresh_token import RefreshToken
from src.models.user import User

REFRESH_TOKEN_TTL_DAYS = 7  # matches Phase_12 SEC-012's design sequence diagram


def _hash_refresh_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class IssuedSession:
    access_token: str
    refresh_token: str


def issue_session(db_session: Session, user: User) -> IssuedSession:
    """Starts a brand-new rotation family (family_id = a fresh UUID, parent_id = None) -- for
    /login and /mfa/{confirm,verify}. A *rotation* of an existing family is handled directly in
    src/api/routers/auth.py::refresh(), not here, since that path reads and mutates an existing
    row rather than starting fresh."""
    access_token = create_access_token(user_id=str(user.id), role=user.role)

    raw_refresh_token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    db_session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=_hash_refresh_token(raw_refresh_token),
            family_id=uuid.uuid4(),
            parent_id=None,
            expires_at=now + timedelta(days=REFRESH_TOKEN_TTL_DAYS),
        )
    )
    db_session.flush()
    return IssuedSession(access_token=access_token, refresh_token=raw_refresh_token)
