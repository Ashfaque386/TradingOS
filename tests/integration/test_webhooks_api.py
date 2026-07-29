"""REL-007 E7.7 webhook gateway integration tests against the real FastAPI app + real
Postgres/Redis/Vault. Secrets are written to Vault directly (not `.env`, which the
`@lru_cache`d Settings object reads only once at process startup) -- same pattern as
scripts/seed_vault_webhook_secrets.py, just done in-test.
"""

import hashlib
import hmac
import json
import uuid

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from src.api.main import app
from src.core import vault
from src.core.db import get_session
from src.models.webhook import WebhookEvent

client = TestClient(app)


def _cleanup_events(channel: str) -> None:
    with get_session() as session:
        session.query(WebhookEvent).filter(WebhookEvent.channel == channel).delete()
        session.commit()


def test_telegram_webhook_accepts_a_correctly_signed_update():
    secret = f"test-secret-{uuid.uuid4()}"
    # A fresh, unique update_id every run -- the real replay-prevention feature this epic builds
    # would otherwise (correctly) treat a re-run of this test using a fixed ID as an idempotent
    # no-op, and this test's own leftover Redis dedup key from a prior run would break it.
    update_id = int(uuid.uuid4().int % 1_000_000_000)
    vault.write_webhook_secret("telegram", {"secret_token": secret})
    try:
        response = client.post(
            "/api/v1/webhooks/telegram",
            json={"update_id": update_id, "message": {"chat": {"id": 999}, "text": "hello"}},
            headers={"X-Telegram-Bot-Api-Secret-Token": secret},
        )
        assert response.status_code == 200
        assert response.json() == {"ok": True}

        with get_session() as session:
            row = (
                session.query(WebhookEvent)
                .filter(WebhookEvent.channel == "Telegram")
                .order_by(WebhookEvent.id.desc())
                .first()
            )
            assert row is not None
            assert row.user_message_raw["update_id"] == update_id
    finally:
        vault.delete_webhook_secret("telegram")
        _cleanup_events("Telegram")


def test_telegram_webhook_rejects_a_bad_signature():
    secret = f"test-secret-{uuid.uuid4()}"
    vault.write_webhook_secret("telegram", {"secret_token": secret})
    try:
        response = client.post(
            "/api/v1/webhooks/telegram",
            json={"update_id": 1, "message": {"chat": {"id": 1}}},
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-secret"},
        )
        assert response.status_code == 401
    finally:
        vault.delete_webhook_secret("telegram")


def test_telegram_webhook_replay_is_an_idempotent_no_op():
    secret = f"test-secret-{uuid.uuid4()}"
    vault.write_webhook_secret("telegram", {"secret_token": secret})
    update_id = 99999
    try:
        first = client.post(
            "/api/v1/webhooks/telegram",
            json={"update_id": update_id, "message": {"chat": {"id": 1}}},
            headers={"X-Telegram-Bot-Api-Secret-Token": secret},
        )
        assert first.status_code == 200

        with get_session() as session:
            count_after_first = (
                session.query(WebhookEvent).filter(WebhookEvent.channel == "Telegram").count()
            )

        second = client.post(
            "/api/v1/webhooks/telegram",
            json={"update_id": update_id, "message": {"chat": {"id": 1}}},
            headers={"X-Telegram-Bot-Api-Secret-Token": secret},
        )
        assert second.status_code == 200

        with get_session() as session:
            count_after_second = (
                session.query(WebhookEvent).filter(WebhookEvent.channel == "Telegram").count()
            )
        assert count_after_second == count_after_first
    finally:
        vault.delete_webhook_secret("telegram")
        _cleanup_events("Telegram")


def test_discord_ping_handshake_is_echoed_back():
    private_key = Ed25519PrivateKey.generate()
    public_key_hex = private_key.public_key().public_bytes_raw().hex()
    vault.write_webhook_secret("discord", {"public_key": public_key_hex})
    try:
        raw_body = json.dumps({"type": 1}).encode("utf-8")
        timestamp = "1700000000"
        signature = private_key.sign(timestamp.encode("utf-8") + raw_body)

        response = client.post(
            "/api/v1/webhooks/discord",
            content=raw_body,
            headers={
                "X-Signature-Ed25519": signature.hex(),
                "X-Signature-Timestamp": timestamp,
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 200
        assert response.json() == {"type": 1}
    finally:
        vault.delete_webhook_secret("discord")


def test_discord_webhook_rejects_a_bad_signature():
    private_key = Ed25519PrivateKey.generate()
    public_key_hex = private_key.public_key().public_bytes_raw().hex()
    vault.write_webhook_secret("discord", {"public_key": public_key_hex})
    try:
        raw_body = json.dumps({"type": 1}).encode("utf-8")
        response = client.post(
            "/api/v1/webhooks/discord",
            content=raw_body,
            headers={
                "X-Signature-Ed25519": "00" * 64,
                "X-Signature-Timestamp": "1700000000",
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 401
    finally:
        vault.delete_webhook_secret("discord")


def test_whatsapp_verification_challenge_echoes_back_when_token_matches(monkeypatch):
    from src.core.config import get_settings

    monkeypatch.setattr(get_settings(), "whatsapp_verify_token", "real-verify-token")
    response = client.get(
        "/api/v1/webhooks/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "real-verify-token",
            "hub.challenge": "challenge-123",
        },
    )
    assert response.status_code == 200
    assert response.text == "challenge-123"


def test_whatsapp_verification_challenge_rejects_wrong_token(monkeypatch):
    from src.core.config import get_settings

    monkeypatch.setattr(get_settings(), "whatsapp_verify_token", "real-verify-token")
    response = client.get(
        "/api/v1/webhooks/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong-token",
            "hub.challenge": "challenge-123",
        },
    )
    assert response.status_code == 403


def test_whatsapp_webhook_accepts_a_correctly_signed_message():
    app_secret = f"test-app-secret-{uuid.uuid4()}"
    vault.write_webhook_secret("whatsapp", {"app_secret": app_secret})
    try:
        # A fresh, unique message id every run -- same reasoning as the Telegram test above.
        message_id = f"wamid.{uuid.uuid4()}"
        payload = {
            "entry": [
                {"changes": [{"value": {"messages": [{"id": message_id, "from": "911234567890"}]}}]}
            ]
        }
        raw_body = json.dumps(payload).encode("utf-8")
        signature = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

        response = client.post(
            "/api/v1/webhooks/whatsapp",
            content=raw_body,
            headers={
                "X-Hub-Signature-256": f"sha256={signature}",
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 200

        with get_session() as session:
            row = (
                session.query(WebhookEvent)
                .filter(WebhookEvent.channel == "WhatsApp")
                .order_by(WebhookEvent.id.desc())
                .first()
            )
            assert row is not None
    finally:
        vault.delete_webhook_secret("whatsapp")
        _cleanup_events("WhatsApp")


def test_whatsapp_webhook_rejects_a_bad_signature():
    app_secret = f"test-app-secret-{uuid.uuid4()}"
    vault.write_webhook_secret("whatsapp", {"app_secret": app_secret})
    try:
        raw_body = json.dumps({"entry": []}).encode("utf-8")
        response = client.post(
            "/api/v1/webhooks/whatsapp",
            content=raw_body,
            headers={
                "X-Hub-Signature-256": "sha256=" + "0" * 64,
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 401
    finally:
        vault.delete_webhook_secret("whatsapp")
