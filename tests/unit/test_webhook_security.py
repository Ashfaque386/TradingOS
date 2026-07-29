"""src/core/webhook_security.py unit tests (REL-007 E7.7, SEC-025..028) -- real crypto against
synthetic signed payloads, no live bot account needed for any of these.
"""

import hashlib
import hmac

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.core.webhook_security import (
    verify_discord_signature,
    verify_telegram_secret_token,
    verify_whatsapp_signature,
)


def test_telegram_correct_secret_is_accepted():
    assert verify_telegram_secret_token("real-secret", expected_secret="real-secret") is True


def test_telegram_wrong_secret_is_rejected():
    assert verify_telegram_secret_token("wrong", expected_secret="real-secret") is False


def test_telegram_missing_header_is_rejected():
    assert verify_telegram_secret_token(None, expected_secret="real-secret") is False


def _discord_keypair() -> tuple[Ed25519PrivateKey, str]:
    private_key = Ed25519PrivateKey.generate()
    public_key_hex = private_key.public_key().public_bytes_raw().hex()
    return private_key, public_key_hex


def test_discord_correctly_signed_payload_is_accepted():
    private_key, public_key_hex = _discord_keypair()
    raw_body = b'{"type": 2}'
    timestamp = "1700000000"
    signature = private_key.sign(timestamp.encode("utf-8") + raw_body)
    assert (
        verify_discord_signature(
            raw_body, signature.hex(), timestamp, public_key_hex=public_key_hex
        )
        is True
    )


def test_discord_tampered_payload_is_rejected():
    private_key, public_key_hex = _discord_keypair()
    raw_body = b'{"type": 2}'
    timestamp = "1700000000"
    signature = private_key.sign(timestamp.encode("utf-8") + raw_body)
    tampered_body = b'{"type": 999}'
    assert (
        verify_discord_signature(
            tampered_body, signature.hex(), timestamp, public_key_hex=public_key_hex
        )
        is False
    )


def test_discord_wrong_public_key_is_rejected():
    private_key, _real_public_key_hex = _discord_keypair()
    _wrong_private_key, wrong_public_key_hex = _discord_keypair()
    raw_body = b'{"type": 2}'
    timestamp = "1700000000"
    signature = private_key.sign(timestamp.encode("utf-8") + raw_body)
    assert (
        verify_discord_signature(
            raw_body, signature.hex(), timestamp, public_key_hex=wrong_public_key_hex
        )
        is False
    )


def test_discord_malformed_signature_hex_is_rejected_not_raised():
    _private_key, public_key_hex = _discord_keypair()
    assert (
        verify_discord_signature(
            b"body", "not-valid-hex", "1700000000", public_key_hex=public_key_hex
        )
        is False
    )


def test_whatsapp_correctly_signed_payload_is_accepted():
    app_secret = "real-app-secret"
    raw_body = b'{"entry": []}'
    expected_hex = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    header = f"sha256={expected_hex}"
    assert verify_whatsapp_signature(raw_body, header, app_secret=app_secret) is True


def test_whatsapp_tampered_payload_is_rejected():
    app_secret = "real-app-secret"
    raw_body = b'{"entry": []}'
    expected_hex = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    header = f"sha256={expected_hex}"
    tampered_body = b'{"entry": ["tampered"]}'
    assert verify_whatsapp_signature(tampered_body, header, app_secret=app_secret) is False


def test_whatsapp_missing_prefix_is_rejected():
    assert verify_whatsapp_signature(b"body", "deadbeef", app_secret="secret") is False
