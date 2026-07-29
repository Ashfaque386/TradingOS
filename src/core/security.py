"""JWT auth + password hashing. Phase_12_Security_Design.md §2's original exit-criteria gap list
for this module: JWT signed via Vault's Transit engine (SEC-011), mandatory MFA for SA/PM/RM
(SEC-014), refresh-token rotation (SEC-012), dual-control (SEC-013), device fingerprinting
(SEC-015), and an OPA/Casbin policy engine (SEC-017). SEC-011 is now real (REL-007 E7.2, this
module + src/core/vault_transit.py) -- JWTs are signed/verified via a real Vault Transit
`ecdsa-p256` key, not a static env-var secret; rotating that key genuinely invalidates every
previously-issued token (see vault_transit.py's module docstring for the mechanism). The rest of
the original list closes across the rest of REL-007 (MFA: src/api/routers/mfa.py; refresh
tokens: src/models/refresh_token.py; dual-control: src/api/routers/risk_limits.py; policy engine:
src/core/policy.py); device fingerprinting (SEC-015) remains deferred past REL-007, not in its
scope.

`ACCESS_TOKEN_TTL_MINUTES`/`ALL_ROLES` are unchanged. `jwt_secret_key`/`jwt_algorithm`
(src/core/config.py) are kept only as a historical record of the pre-Transit scheme -- nothing in
this module reads them anymore, and there is deliberately no fallback path that would sign or
verify a token without Vault: a Vault outage must be a loud failure at the auth boundary, not a
silent downgrade to a weaker signing scheme.

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

import base64
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt

from src.core import vault_transit
from src.core.vault_transit import VaultTransitUnavailableError

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


_JWT_ALG = "ES256"


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _create_token(claims: dict[str, Any], *, ttl_minutes: float) -> str:
    """Builds a JWS by hand -- Vault Transit signs raw bytes, not JOSE, so there's no
    jose.jwt.encode()-equivalent to call through to it. The key version must be chosen *before*
    signing (see vault_transit.sign()'s docstring): it's part of the header, and the header is
    part of what gets signed. Shared by create_access_token and create_mfa_pending_token
    (src/api/routers/mfa.py) -- only the claims and TTL differ between the two."""
    now = datetime.now(UTC)
    payload = {
        **claims,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ttl_minutes)).timestamp()),
    }
    kid = vault_transit.current_key_version()
    header = {"alg": _JWT_ALG, "typ": "JWT", "kid": str(kid)}
    header_b64 = _b64url_encode(json.dumps(header, sort_keys=True).encode("utf-8"))
    payload_b64 = _b64url_encode(json.dumps(payload, sort_keys=True).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    raw_signature = vault_transit.sign(signing_input, key_version=kid)
    signature_b64 = _b64url_encode(raw_signature)
    return f"{header_b64}.{payload_b64}.{signature_b64}"


def create_access_token(*, user_id: str, role: str) -> str:
    return _create_token({"sub": user_id, "role": role}, ttl_minutes=ACCESS_TOKEN_TTL_MINUTES)


# REL-007 E7.1 (SEC-014): roles that must complete MFA before a real access token is issued.
# ReadOnlyAuditor is deliberately excluded -- SEC-014's own text only mandates MFA for
# SystemAdministrator/PortfolioManager/RiskManager.
#
# DISABLED per explicit user request (2026-07-28) -- the frontend MFA UI is real and working
# (src/api/routers/mfa.py's enroll/confirm/verify are unchanged and still fully functional, only
# not *enforced*), but the user wants it off for now and re-enabled later. To turn enforcement
# back on, restore the frozenset below to
# `frozenset({ROLE_SYSTEM_ADMINISTRATOR, ROLE_PORTFOLIO_MANAGER, ROLE_RISK_MANAGER})` -- nothing
# else needs to change.
MFA_MANDATORY_ROLES: frozenset[str] = frozenset()

MFA_PENDING_TOKEN_TTL_MINUTES = 5
_MFA_PENDING_SCOPE = "mfa_pending"


def create_mfa_pending_token(*, user_id: str, role: str) -> str:
    """A short-lived, narrowly-scoped token issued after a correct password but before MFA is
    satisfied -- proves "this password was correct" without being a usable access token. Only
    src/api/deps.py::get_mfa_pending_user checks the `scope` claim; decode_access_token itself
    doesn't care (a pending token is structurally just a JWT with a different claim shape)."""
    return _create_token(
        {"sub": user_id, "role": role, "scope": _MFA_PENDING_SCOPE},
        ttl_minutes=MFA_PENDING_TOKEN_TTL_MINUTES,
    )


class InvalidTokenError(Exception):
    """Raised for any decode failure (expired, bad signature, malformed, or signed by a key
    version below the current min_decryption_version -- i.e. a rotated-away key) -- callers
    translate this to a 401, never distinguishing the reason to the client (no signal to an
    attacker about which part of their forged token was wrong)."""


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
        header = json.loads(_b64url_decode(header_b64))
        payload: dict[str, Any] = json.loads(_b64url_decode(payload_b64))
        raw_signature = _b64url_decode(signature_b64)
        kid = int(header["kid"])
    except (ValueError, KeyError, TypeError) as exc:
        raise InvalidTokenError("malformed token") from exc

    if header.get("alg") != _JWT_ALG:
        raise InvalidTokenError(f"unexpected alg {header.get('alg')!r}")

    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    try:
        verified = vault_transit.verify(signing_input, raw_signature, kid)
        current_min_version = vault_transit.min_decryption_version()
    except VaultTransitUnavailableError as exc:
        # Fail closed: a cold/stale local cache plus an unreachable Vault must never be treated
        # as "verification skipped, let it through" -- surface it as the same InvalidTokenError
        # every other decode failure raises, so callers (src/api/deps.py::get_current_user) don't
        # need a second except clause to stay safe.
        raise InvalidTokenError(f"could not verify signature: {exc}") from exc
    if not verified:
        raise InvalidTokenError("signature verification failed")

    # Rotation enforcement: a cryptographically valid signature from a key version Vault has
    # since been told to stop trusting (rotate_key() raised min_decryption_version past it) must
    # still be rejected -- this is the actual mechanism behind "rotating the key invalidates old
    # tokens", not the signature check alone.
    if kid < current_min_version:
        raise InvalidTokenError(f"token signed with rotated-away key version {kid}")

    exp = payload.get("exp")
    if exp is None or datetime.now(UTC).timestamp() > exp:
        raise InvalidTokenError("token expired")

    return payload
