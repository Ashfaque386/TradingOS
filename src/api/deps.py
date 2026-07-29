"""FastAPI auth dependencies (Phase 4 exit-criteria gap -- see src/core/security.py's module
docstring for what this does and doesn't cover relative to the full Phase_12 design).
"""

import uuid
from collections.abc import Callable
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.routing import Route

from src.core import policy
from src.core.audit import write_audit_entry
from src.core.db import get_session
from src.core.security import InvalidTokenError, decode_access_token
from src.models.user import User

_bearer_scheme = HTTPBearer(auto_error=False)

_CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def _decode_and_load_user(token: str) -> tuple[dict[str, Any], User]:
    """Shared by get_current_user and get_mfa_pending_user -- the two differ only in which
    `scope` claim they require, not in how a token is decoded or a User loaded from it."""
    try:
        payload = decode_access_token(token)
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
        return payload, user


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> User:
    if credentials is None:
        raise _CREDENTIALS_ERROR
    payload, user = _decode_and_load_user(credentials.credentials)
    # A pending-MFA token is structurally a valid JWT, but must never authenticate a normal
    # request -- reject it exactly like decode_access_token would reject a signature failure,
    # rather than let a user with only a correct password (not a completed MFA challenge) reach
    # any endpoint that isn't part of the MFA flow itself.
    if payload.get("scope") == "mfa_pending":
        raise _CREDENTIALS_ERROR
    return user


def get_mfa_pending_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> User:
    """REL-007 E7.1: the counterpart to get_current_user for src/api/routers/mfa.py's
    enroll/confirm/verify endpoints -- requires a pending-MFA token (scope="mfa_pending"), not a
    full access token, and rejects a full access token exactly as strictly (a completed session
    has no business re-entering the MFA challenge flow)."""
    if credentials is None:
        raise _CREDENTIALS_ERROR
    payload, user = _decode_and_load_user(credentials.credentials)
    if payload.get("scope") != "mfa_pending":
        raise _CREDENTIALS_ERROR
    return user


def get_user_any_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> User:
    """REL-007 E7.1: for src/api/routers/mfa.py's `/enroll` only -- voluntary MFA enrollment is
    allowed for any authenticated user regardless of whether their session is a full access
    token or a pending-MFA one (a mandatory-role user must be able to enroll *during* their
    first login's pending-MFA window, not only after already holding a full session)."""
    if credentials is None:
        raise _CREDENTIALS_ERROR
    _payload, user = _decode_and_load_user(credentials.credentials)
    return user


def require_role(*allowed_roles: str, audit_denials: bool = False) -> Callable[..., User]:
    """Dependency factory:
    `Depends(require_role(ROLE_SYSTEM_ADMINISTRATOR, ROLE_PORTFOLIO_MANAGER))`.

    REL-007 E7.5 (SEC-017): the actual authorization decision is now made by
    src/core/policy.py's Casbin enforcer (policy.csv), not by checking `allowed_roles` directly
    -- but every call site's signature and arguments are unchanged, so `allowed_roles` is now
    also stashed on the returned dependency (`_check.declared_roles`) purely so
    tests/unit/test_policy_consistency.py can catch drift between what a call site *declares*
    and what policy.csv actually *grants* for its routes. This is what keeps the policy
    "diffable in code review" (SEC-017's own phrase) without rewriting all 5 call sites.

    `audit_denials=True` writes a real AuditLog row (REL-006 E6.2) on a 403. Deliberately
    opt-in, not automatic on every use of this dependency: AUDIT_LOG is append-only forever (no
    purge, per DB-014), so logging every denied request risks filling it with noise from a
    misconfigured frontend retry loop. Pass it only for genuinely sensitive endpoints
    (kill-switch, strategy promotion, audit-log access)."""

    def _check(request: Request, user: User = Depends(get_current_user)) -> User:
        route = request.scope.get("route")
        # Casbin policy.csv is keyed by FastAPI's resolved route *template*
        # ("/api/v1/strategies/{strategy_id}/promote"), not the raw request URL with real IDs
        # substituted in -- request.scope["route"] is set by Starlette's routing before any
        # dependency runs, so this is always available for a real request; the raw-path fallback
        # only matters for a dependency invoked outside real routing (e.g. a unit test calling
        # `_check` directly), where no policy row could match it anyway.
        route_template = route.path if isinstance(route, Route) else request.url.path
        if not policy.is_allowed(user.role, route_template, request.method):
            if audit_denials:
                with get_session() as session:
                    write_audit_entry(
                        session,
                        actor_type="Human",
                        actor_id=user.email,
                        action="RBAC_DENIED",
                        entity_type="Endpoint",
                        after_state={"path": request.url.path, "role": user.role},
                    )
                    session.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role}' is not permitted to perform this action.",
            )
        return user

    _check.declared_roles = frozenset(allowed_roles)  # type: ignore[attr-defined]
    return _check
