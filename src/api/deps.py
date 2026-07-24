"""FastAPI auth dependencies (Phase 4 exit-criteria gap -- see src/core/security.py's module
docstring for what this does and doesn't cover relative to the full Phase_12 design).
"""

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.core.db import get_session
from src.core.security import InvalidTokenError, decode_access_token
from src.models.user import User

_bearer_scheme = HTTPBearer(auto_error=False)

_CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> User:
    if credentials is None:
        raise _CREDENTIALS_ERROR
    try:
        payload = decode_access_token(credentials.credentials)
    except InvalidTokenError as exc:
        raise _CREDENTIALS_ERROR from exc

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise _CREDENTIALS_ERROR from exc

    with get_session() as session:
        user = session.get(User, user_id)
        if user is None or not user.is_active:
            raise _CREDENTIALS_ERROR
        session.expunge(user)
        return user


def require_role(*allowed_roles: str):
    """Dependency factory: `Depends(require_role(ROLE_SYSTEM_ADMINISTRATOR, ROLE_PORTFOLIO_MANAGER))`.
    Plain-code role check, not the OPA/Casbin policy engine Phase_12 SEC-017 calls for -- deferred,
    documented in src/core/security.py's module docstring."""

    def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role}' is not permitted to perform this action.",
            )
        return user

    return _check
