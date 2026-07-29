"""src/core/security.py unit tests: password hashing only. JWT create/decode round-trips moved
to tests/integration/test_vault_transit.py (REL-007 E7.2) -- they now sign/verify via a real
Vault Transit key and can no longer run hermetically without live Vault.

Covers the real password-hashing bug found and fixed earlier this session (passlib 1.7.4 broken
against bcrypt>=4.1 -- see the module docstring) via a password right at bcrypt's 72-byte limit.
"""

import pytest

from src.core.security import hash_password, verify_password


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
