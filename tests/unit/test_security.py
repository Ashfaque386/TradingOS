"""src/core/security.py unit tests (Phase 4 exit-criteria gap: JWT auth). Covers the real
password-hashing bug found and fixed this session (passlib 1.7.4 broken against bcrypt>=4.1 --
see the module docstring) via a password right at bcrypt's 72-byte limit, and real JWT
create/decode round-trips including expiry.
"""

from datetime import UTC, datetime, timedelta

import pytest
from jose import jwt

from src.core.config import get_settings
from src.core.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_a_correct_password_verifies_and_a_wrong_one_does_not():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed) is True
    assert verify_password("wrong password", hashed) is False


def test_a_72_byte_password_hashes_and_verifies_without_the_known_passlib_bcrypt_bug():
    password = "x" * 72
    hashed = hash_password(password)
    assert verify_password(password, hashed) is True


def test_a_password_over_72_bytes_is_rejected_loudly_rather_than_silently_truncated():
    with pytest.raises(ValueError):
        hash_password("x" * 73)


def test_two_hashes_of_the_same_password_differ_real_random_salt():
    a = hash_password("same-password")
    b = hash_password("same-password")
    assert a != b
    assert verify_password("same-password", a)
    assert verify_password("same-password", b)


def test_a_real_token_round_trips_with_its_claims_intact():
    token = create_access_token(user_id="11111111-1111-1111-1111-111111111111", role="SystemAdministrator")
    payload = decode_access_token(token)
    assert payload["sub"] == "11111111-1111-1111-1111-111111111111"
    assert payload["role"] == "SystemAdministrator"


def test_an_expired_token_is_rejected():
    # Encodes directly with jose rather than create_access_token, so the token's `exp` claim can
    # be set in the past without needing to fake the system clock.
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": "11111111-1111-1111-1111-111111111111",
        "role": "PortfolioManager",
        "iat": now - timedelta(minutes=30),
        "exp": now - timedelta(minutes=15),
    }
    expired_token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    with pytest.raises(InvalidTokenError):
        decode_access_token(expired_token)


def test_a_tampered_token_is_rejected():
    token = create_access_token(user_id="11111111-1111-1111-1111-111111111111", role="RiskManager")
    tampered = token[:-4] + ("A" * 4 if token[-4:] != "AAAA" else "BBBB")
    with pytest.raises(InvalidTokenError):
        decode_access_token(tampered)
