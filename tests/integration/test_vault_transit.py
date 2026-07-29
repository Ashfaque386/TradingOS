"""Vault Transit JWT signing (REL-007 E7.2, SEC-011) against the real dev Vault container --
exit criterion 2: "JWT signing keys are genuinely issued by Vault Transit, not a static env var;
rotating the Transit key invalidates old tokens as expected."

Moved here from tests/unit/test_security.py: JWT create/decode now signs/verifies via a real
Vault Transit key and can no longer run hermetically without live Vault.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest

from src.core import security, vault_transit
from src.core.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
)
from src.core.vault_transit import VaultTransitUnavailableError


def test_ensure_transit_key_is_idempotent():
    vault_transit.ensure_transit_key()
    vault_transit.ensure_transit_key()  # second call must not raise


def test_sign_and_verify_round_trip_and_a_tampered_payload_fails():
    kid = vault_transit.current_key_version()
    payload = b"a real payload, signed for real"
    raw_signature = vault_transit.sign(payload, key_version=kid)
    assert vault_transit.verify(payload, raw_signature, kid) is True
    assert vault_transit.verify(b"a tampered payload, signed for real", raw_signature, kid) is False


def test_a_real_token_round_trips_with_its_claims_intact():
    token = create_access_token(
        user_id="11111111-1111-1111-1111-111111111111", role="SystemAdministrator"
    )
    payload = decode_access_token(token)
    assert payload["sub"] == "11111111-1111-1111-1111-111111111111"
    assert payload["role"] == "SystemAdministrator"


def test_an_expired_token_is_rejected():
    # Built directly via the module's own (private, but this is the one legitimate reason to
    # reach for them) JWS helpers rather than create_access_token, so `exp` can be set in the
    # past without faking the system clock.
    kid = vault_transit.current_key_version()
    now = datetime.now(UTC)
    payload = {
        "sub": "11111111-1111-1111-1111-111111111111",
        "role": "PortfolioManager",
        "iat": int((now - timedelta(minutes=30)).timestamp()),
        "exp": int((now - timedelta(minutes=15)).timestamp()),
    }
    header = {"alg": "ES256", "typ": "JWT", "kid": str(kid)}
    header_b64 = security._b64url_encode(json.dumps(header, sort_keys=True).encode("utf-8"))
    payload_b64 = security._b64url_encode(json.dumps(payload, sort_keys=True).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    raw_signature = vault_transit.sign(signing_input, key_version=kid)
    signature_b64 = security._b64url_encode(raw_signature)
    expired_token = f"{header_b64}.{payload_b64}.{signature_b64}"

    with pytest.raises(InvalidTokenError):
        decode_access_token(expired_token)


def test_a_tampered_token_is_rejected():
    token = create_access_token(user_id="11111111-1111-1111-1111-111111111111", role="RiskManager")
    tampered = token[:-4] + ("A" * 4 if token[-4:] != "AAAA" else "BBBB")
    with pytest.raises(InvalidTokenError):
        decode_access_token(tampered)


def test_rotating_the_transit_key_invalidates_tokens_signed_before_the_rotation():
    token_a = create_access_token(
        user_id="22222222-2222-2222-2222-222222222222", role="RiskManager"
    )
    assert decode_access_token(token_a)["sub"] == "22222222-2222-2222-2222-222222222222"

    vault_transit.rotate_key()

    token_b = create_access_token(
        user_id="33333333-3333-3333-3333-333333333333", role="RiskManager"
    )
    assert decode_access_token(token_b)["sub"] == "33333333-3333-3333-3333-333333333333"
    with pytest.raises(InvalidTokenError):
        decode_access_token(token_a)


def test_verify_fails_closed_on_a_cache_miss_against_unreachable_vault():
    from src.core.config import Settings

    unreachable = Settings(
        vault_addr="http://vault-does-not-exist.invalid:8200", vault_token="bogus"
    )
    # A key version guaranteed absent from any warm cache forces a refresh attempt.
    with pytest.raises(VaultTransitUnavailableError):
        vault_transit.verify(b"payload", b"\x00" * 64, 999_999, settings=unreachable)
