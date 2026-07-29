"""Vault Transit-issued JWT signing (REL-007 E7.2, SEC-011): closes the one gap
`src/core/security.py`'s own module docstring named -- "JWT signed via Vault's Transit engine"
-- by replacing the static `Settings.jwt_secret_key` HS256 secret with a real Vault Transit
`ecdsa-p256` key, confirmed real by an actual sign/verify round-trip against the live dev Vault
container before this module was written (not assumed from documentation).

Transit's `sign_data`/`verify_signed_data` operate on raw bytes, not JOSE, and return/expect
ASN.1 DER-encoded ECDSA signatures (`vault:v<N>:<base64 DER>`) while a JWS ES256 signature is the
raw fixed-length r||s encoding -- both directions need explicit conversion via
`cryptography.hazmat.primitives.asymmetric.utils`.

Verification never calls Vault on the hot path: `read_key` returns every historical key
version's public key PEM plus the key's current `min_decryption_version`, so this module caches
that (60s TTL) and verifies locally with `cryptography`. `min_decryption_version` is what makes
`rotate_key()` genuinely invalidate old tokens -- `decode_access_token` (src/core/security.py)
rejects any token whose `kid` (key version) is below the cached `min_decryption_version`, even
though a stale-cache verify might otherwise still succeed cryptographically.

Fails CLOSED, deliberately unlike this module's sibling `vault.py` (which fails open for
optional broker/LLM credentials -- the system should keep working without them). JWT signing is
the one thing between an attacker and every authenticated endpoint; a Vault outage at
token-issuance time must produce a loud 503 (VaultTransitUnavailableError), never a fallback to
an insecure or absent signature.

Known, accepted consequence of dev Vault's in-memory-only storage (no `volumes:` on the `vault`
compose service -- confirmed in docker-compose.yml, wiped on every container restart): a Vault
restart deletes this Transit key entirely, and every previously-issued access token becomes
permanently unverifiable -- equivalent to a forced global logout. `src/api/main.py`'s
`lifespan()` calls `ensure_transit_key()` on every app boot so the key (and therefore login) is
self-healing after a wipe, at the cost of that logout. This is a materially bigger consequence
than the broker-credential fail-open gap `vault.py` already documents, called out here on its
own rather than folded into that note.
"""

from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass, field

import hvac
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric import utils as asym_utils
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePublicKey

from src.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

TRANSIT_KEY_NAME = "tradingos-jwt-signing"
_CACHE_TTL_SECONDS = 60


class VaultTransitUnavailableError(Exception):
    """Raised when Vault/Transit is unreachable at a point where failing open would be a real
    security regression (token issuance, or verification with no usable cached key)."""


def _client(settings: Settings) -> hvac.Client:
    if not settings.vault_addr or not settings.vault_token:
        raise VaultTransitUnavailableError("Vault is not configured (vault_addr/vault_token unset)")
    client = hvac.Client(url=settings.vault_addr, token=settings.vault_token)
    try:
        if not client.is_authenticated():
            raise VaultTransitUnavailableError(f"Vault at {settings.vault_addr} rejected the token")
    except VaultTransitUnavailableError:
        raise
    except Exception as exc:  # noqa: BLE001 -- any transport failure, translated to our own type
        raise VaultTransitUnavailableError(
            f"Vault unreachable at {settings.vault_addr}: {exc}"
        ) from exc
    return client


def ensure_transit_key(settings: Settings | None = None) -> None:
    """Idempotent setup: enables the transit secrets engine and creates the signing key if
    either doesn't exist yet. Safe to call on every app boot (see module docstring)."""
    settings = settings or get_settings()
    client = _client(settings)
    try:
        client.secrets.transit.read_key(name=TRANSIT_KEY_NAME)
        return  # key already exists
    except hvac.exceptions.InvalidPath:
        pass  # engine not mounted or key not created yet -- fall through
    try:
        client.sys.enable_secrets_engine(backend_type="transit")
    except hvac.exceptions.InvalidRequest as exc:
        if "path is already in use" not in str(exc):
            raise
    client.secrets.transit.create_key(
        name=TRANSIT_KEY_NAME, key_type="ecdsa-p256", exportable=False
    )


@dataclass
class _TransitKeyState:
    public_keys: dict[int, EllipticCurvePublicKey] = field(default_factory=dict)
    min_decryption_version: int = 1
    latest_version: int = 1
    fetched_at: float = 0.0


_cache = _TransitKeyState()


def _refresh_cache(settings: Settings) -> None:
    client = _client(settings)
    response = client.secrets.transit.read_key(name=TRANSIT_KEY_NAME)
    data = response["data"]
    public_keys: dict[int, EllipticCurvePublicKey] = {}
    for version_str, key_info in data["keys"].items():
        pem = key_info["public_key"].encode("utf-8")
        loaded = serialization.load_pem_public_key(pem)
        if not isinstance(loaded, EllipticCurvePublicKey):
            raise VaultTransitUnavailableError(
                f"Transit key {TRANSIT_KEY_NAME} version {version_str} is not an EC public key"
            )
        public_keys[int(version_str)] = loaded
    _cache.public_keys = public_keys
    _cache.min_decryption_version = data["min_decryption_version"]
    _cache.latest_version = data["latest_version"]
    _cache.fetched_at = time.monotonic()


def _cache_is_fresh() -> bool:
    return bool(_cache.public_keys) and (time.monotonic() - _cache.fetched_at) < _CACHE_TTL_SECONDS


def _public_key_for(kid: int, settings: Settings) -> EllipticCurvePublicKey | None:
    if not _cache_is_fresh() or kid not in _cache.public_keys:
        _refresh_cache(settings)
    return _cache.public_keys.get(kid)


def min_decryption_version(settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    if not _cache_is_fresh():
        _refresh_cache(settings)
    return _cache.min_decryption_version


def current_key_version(settings: Settings | None = None) -> int:
    """The version JWS signing should target -- fetched *before* signing so the JWT header's
    `kid` (part of what gets signed) is known upfront, rather than discovered only after the
    fact from Vault's response. See `sign()`'s docstring for why this two-step matters."""
    settings = settings or get_settings()
    if not _cache_is_fresh():
        _refresh_cache(settings)
    return _cache.latest_version


def sign(payload_bytes: bytes, *, key_version: int, settings: Settings | None = None) -> bytes:
    """Signs with an explicit `key_version` (from `current_key_version()`), not Vault's default
    "always latest" behavior -- a JWS's header (which names the kid) must be fixed *before*
    signing, since the header itself is part of what gets signed, so the caller has to choose
    the version first and then sign, not the other way around. Returns the raw 64-byte r||s
    ECDSA signature."""
    settings = settings or get_settings()
    client = _client(settings)
    b64_payload = base64.b64encode(payload_bytes).decode("ascii")
    response = client.secrets.transit.sign_data(
        name=TRANSIT_KEY_NAME,
        hash_input=b64_payload,
        hash_algorithm="sha2-256",
        key_version=key_version,
    )
    sig_field: str = response["data"]["signature"]  # "vault:v<N>:<base64 DER>"
    _prefix, version_part, b64_der = sig_field.split(":", 2)
    signed_kid = int(version_part[1:])  # "v1" -> 1
    if signed_kid != key_version:
        raise VaultTransitUnavailableError(
            f"requested key_version={key_version} but Vault signed with version {signed_kid}"
        )
    der_sig = base64.b64decode(b64_der)
    r_int, s_int = asym_utils.decode_dss_signature(der_sig)
    return r_int.to_bytes(32, "big") + s_int.to_bytes(32, "big")


def verify(
    payload_bytes: bytes, raw_signature: bytes, kid: int, *, settings: Settings | None = None
) -> bool:
    """Local-only verification against the cached public key for `kid`. Never calls Vault to
    decide the outcome once the cache is warm -- see module docstring."""
    settings = settings or get_settings()
    public_key = _public_key_for(kid, settings)
    if public_key is None:
        return False
    if len(raw_signature) != 64:
        return False
    r_int = int.from_bytes(raw_signature[:32], "big")
    s_int = int.from_bytes(raw_signature[32:], "big")
    der_sig = asym_utils.encode_dss_signature(r_int, s_int)
    try:
        public_key.verify(der_sig, payload_bytes, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature:
        return False
    return True


def rotate_key(settings: Settings | None = None) -> int:
    """Rotates the Transit key and raises its min_decryption_version to the new latest version,
    which is what makes rotation hard-invalidate every token signed with an older key version --
    Vault itself will refuse to verify (and this module's local cache will refuse to trust) a
    signature from a version below that floor. Returns the new version number."""
    settings = settings or get_settings()
    client = _client(settings)
    client.secrets.transit.rotate_key(name=TRANSIT_KEY_NAME)
    read_response = client.secrets.transit.read_key(name=TRANSIT_KEY_NAME)
    new_version: int = read_response["data"]["latest_version"]
    client.secrets.transit.update_key_configuration(
        name=TRANSIT_KEY_NAME, min_decryption_version=new_version
    )
    _refresh_cache(settings)
    return new_version
