"""JWT auth + password hashing (Phase 4 exit-criteria gap: Phase_12_Security_Design.md §2 called
for JWT signed via Vault's Transit engine, mandatory MFA for SA/PM/RM, dual-control, and an
OPA/Casbin policy engine -- Vault and MFA infra don't exist in this environment, so this module
implements the same shape (JWT bearer tokens, role claims) with a local env-var signing secret
(`Settings.jwt_secret_key`, already a documented dev-only placeholder) instead of a Vault-issued
key. MFA, refresh-token rotation/session-family theft detection (SEC-012), dual-control
maker-checker (SEC-013), device fingerprinting (SEC-015), and the OPA/Casbin policy engine
(SEC-017) are explicitly deferred, not silently skipped -- see
Phase_14_Master_Development_Roadmap.md §5.3 for the tracked gap.

Password hashing uses bcrypt directly (the `bcrypt` package, not the exact Argon2id Phase_12
names) -- `passlib[bcrypt]` was already a pinned dependency with nothing consuming it, but
passlib 1.7.4 (its last release, 2020) is broken against bcrypt>=4.1: its version-detection code
reads `bcrypt.__about__.__version__`, an attribute the real `bcrypt` package removed, which
passlib's own compatibility shim then mishandles into a spurious "password cannot be longer than
72 bytes" error on every hash/verify call. This is a known, real incompatibility in an
unmaintained library, confirmed by reproducing it directly against the pinned bcrypt==5.0.0 in
this environment -- not a workaround for a hypothetical problem. Calling `bcrypt` directly
avoids passlib's broken shim entirely.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from jose import JWTError, jwt

from src.core.config import get_settings

# Canonical role strings (Phase_12_Security_Design.md §2.2's RBAC Permission Matrix). The AI CEO
# Agent row in that matrix is an internal service identity, not a human login role, so it's not
# included here -- there is no login flow for it.
ROLE_SYSTEM_ADMINISTRATOR = "SystemAdministrator"
ROLE_PORTFOLIO_MANAGER = "PortfolioManager"
ROLE_RISK_MANAGER = "RiskManager"
ROLE_READ_ONLY_AUDITOR = "ReadOnlyAuditor"

ALL_ROLES = (
    ROLE_SYSTEM_ADMINISTRATOR,
    ROLE_PORTFOLIO_MANAGER,
    ROLE_RISK_MANAGER,
    ROLE_READ_ONLY_AUDITOR,
)

ACCESS_TOKEN_TTL_MINUTES = 15  # matches Phase_12 SEC-011's access-token TTL

# bcrypt's own hard limit -- silently truncating past this (as some libraries do) would make
# `"correct horse battery staple" + anything` hash identically for the discarded remainder, a
# real security footgun, so this is enforced loudly instead.
_MAX_PASSWORD_BYTES = 72


def hash_password(plain_password: str) -> str:
    encoded = plain_password.encode("utf-8")
    if len(encoded) > _MAX_PASSWORD_BYTES:
        raise ValueError(f"password must be at most {_MAX_PASSWORD_BYTES} bytes")
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_access_token(*, user_id: str, role: str) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_TTL_MINUTES),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


class InvalidTokenError(Exception):
    """Raised for any decode failure (expired, bad signature, malformed) -- callers translate
    this to a 401, never distinguishing the reason to the client (no signal to an attacker about
    which part of their forged token was wrong)."""


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise InvalidTokenError(str(exc)) from exc
