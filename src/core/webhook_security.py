"""Per-platform webhook signature verification (REL-007 E7.7 SEC-025..028, REL-027 SEC-047): real
cryptographic verification for each of the four supported inbound webhook sources, genuinely
testable with synthetic signed payloads (real HMAC/Ed25519 primitives) without needing a live
Telegram/Discord/WhatsApp/Slack account or bot registration.

All three verify against the *exact raw request bytes* -- callers (src/api/routers/webhooks.py)
must read `await request.body()` before any JSON parsing and pass those raw bytes here.
Re-serializing a parsed body (even losslessly) can reorder keys or change whitespace and silently
break every one of these checks, since the platform signs the literal bytes it sent.
"""

import hashlib
import hmac

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def verify_telegram_secret_token(header_value: str | None, *, expected_secret: str) -> bool:
    """SEC-025: Telegram doesn't sign the payload -- it echoes back the `secret_token` configured
    at `setWebhook` time in every request's `X-Telegram-Bot-Api-Secret-Token` header. Constant-
    time comparison, same reasoning as password/token comparisons elsewhere in this codebase."""
    if header_value is None:
        return False
    return hmac.compare_digest(header_value, expected_secret)


def verify_discord_signature(
    raw_body: bytes, signature_hex: str | None, timestamp: str | None, *, public_key_hex: str
) -> bool:
    """SEC-026: Ed25519 signature over `timestamp + raw_body`, per Discord's interactions
    security model."""
    if signature_hex is None or timestamp is None:
        return False
    try:
        signature = bytes.fromhex(signature_hex)
        public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        public_key.verify(signature, timestamp.encode("utf-8") + raw_body)
    except (InvalidSignature, ValueError):
        return False
    return True


def verify_whatsapp_signature(
    raw_body: bytes, signature_header: str | None, *, app_secret: str
) -> bool:
    """SEC-027: HMAC-SHA256 over the raw body, header format `sha256=<hex>`."""
    if signature_header is None or not signature_header.startswith("sha256="):
        return False
    provided_hex = signature_header[len("sha256=") :]
    expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(provided_hex, expected)


def verify_slack_signature(
    raw_body: bytes, signature_header: str | None, timestamp: str | None, *, signing_secret: str
) -> bool:
    """REL-027 (SEC-047): Slack's own v0 request-signing scheme -- HMAC-SHA256 over
    `"v0:" + timestamp + ":" + raw_body`, header format `v0=<hex>`
    (https://docs.slack.dev/authentication/verifying-requests-from-slack, verified against
    Slack's current docs, not guessed). The caller is responsible for the separate 5-minute
    replay-window timestamp check Slack's own docs also specify -- this function only verifies
    the signature itself, matching every other verify_* function in this module."""
    if signature_header is None or timestamp is None:
        return False
    if not signature_header.startswith("v0="):
        return False
    base_string = f"v0:{timestamp}:".encode() + raw_body
    expected = (
        "v0=" + hmac.new(signing_secret.encode("utf-8"), base_string, hashlib.sha256).hexdigest()
    )
    return hmac.compare_digest(signature_header, expected)
