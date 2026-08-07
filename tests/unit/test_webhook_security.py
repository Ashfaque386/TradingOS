"""src/core/webhook_security.py unit tests (REL-007 E7.7, SEC-025..028) -- real crypto against
synthetic signed payloads, no live bot account needed for any of these.
"""

import hashlib
import hmac

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.core.webhook_security import (
    verify_discord_signature,
    verify_slack_signature,
    verify_telegram_secret_token,
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


def _slack_signature(signing_secret: str, timestamp: str, raw_body: bytes) -> str:
    base_string = f"v0:{timestamp}:".encode() + raw_body
    return "v0=" + hmac.new(signing_secret.encode("utf-8"), base_string, hashlib.sha256).hexdigest()


def test_slack_correctly_signed_payload_is_accepted():
    signing_secret = "real-signing-secret"
    timestamp = "1700000000"
    raw_body = b'{"type": "event_callback"}'
    signature = _slack_signature(signing_secret, timestamp, raw_body)
    assert (
        verify_slack_signature(raw_body, signature, timestamp, signing_secret=signing_secret)
        is True
    )


def test_slack_tampered_payload_is_rejected():
    signing_secret = "real-signing-secret"
    timestamp = "1700000000"
    raw_body = b'{"type": "event_callback"}'
    signature = _slack_signature(signing_secret, timestamp, raw_body)
    tampered_body = b'{"type": "tampered"}'
    assert (
        verify_slack_signature(tampered_body, signature, timestamp, signing_secret=signing_secret)
        is False
    )


def test_slack_wrong_timestamp_in_base_string_is_rejected():
    # The signature was computed for a different timestamp than the one presented alongside it --
    # the base string ("v0:{timestamp}:{body}") must use the SAME timestamp on both sides.
    signing_secret = "real-signing-secret"
    raw_body = b'{"type": "event_callback"}'
    signature = _slack_signature(signing_secret, "1700000000", raw_body)
    assert (
        verify_slack_signature(raw_body, signature, "1700000001", signing_secret=signing_secret)
        is False
    )


def test_slack_missing_prefix_is_rejected():
    assert (
        verify_slack_signature(b"body", "deadbeef", "1700000000", signing_secret="secret") is False
    )


def test_slack_missing_timestamp_is_rejected():
    assert verify_slack_signature(b"body", "v0=deadbeef", None, signing_secret="secret") is False
