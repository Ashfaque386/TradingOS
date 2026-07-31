"""REL-010 E10.1 webhook-gateway routing tests against the real FastAPI app + real Postgres/
Redis. Signature verification/replay/rate-limit are already covered by
tests/integration/test_webhooks_api.py (REL-007 E7.7) -- these tests cover the NEW behavior this
epic adds: a real message with text gets routed to the CEO Agent's real reply pipeline.

Deliberately does NOT wait for the real LLM reply to complete, same reasoning as
tests/integration/test_chat_api.py's own docstring (a real reply can take minutes on this host)
-- asserts the real synchronous state (WebhookEvent.routed_to_agent populated, a real
"Pending" ChatMessage pair persisted scoped to this one external chat thread), not the eventual
reply content.
"""

import json
import time
import uuid

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from sqlalchemy import select

from src.api.main import app
from src.core import vault
from src.core.db import get_session
from src.models.chat import ChatMessage
from src.models.webhook import WebhookEvent

client = TestClient(app)


def _cleanup(channel: str, chat_key: str) -> None:
    with get_session() as session:
        session.query(ChatMessage).filter(
            ChatMessage.channel == channel,
            ChatMessage.external_metadata["chat_key"].astext == chat_key,
        ).delete(synchronize_session=False)
        session.commit()


def _latest_webhook_event(channel: str) -> WebhookEvent:
    with get_session() as session:
        # order by received_at, not id -- WebhookEvent.id is a random UUID (UUIDPKMixin) with no
        # chronological relationship to insertion order (a real bug found running this exact
        # test file: `ORDER BY id DESC` occasionally returned a different test's row).
        row = session.scalar(
            select(WebhookEvent)
            .where(WebhookEvent.channel == channel)
            .order_by(WebhookEvent.received_at.desc())
        )
        assert row is not None
        session.expunge(row)
        return row


def test_telegram_message_with_text_routes_to_ceo_agent_and_creates_a_pending_reply():
    secret = f"test-secret-{uuid.uuid4()}"
    chat_id = str(uuid.uuid4().int % 1_000_000_000)
    update_id = int(uuid.uuid4().int % 1_000_000_000)
    marker = f"integration-test-{uuid.uuid4()}"
    vault.write_webhook_secret("telegram", {"secret_token": secret})
    try:
        response = client.post(
            "/api/v1/webhooks/telegram",
            json={
                "update_id": update_id,
                "message": {"chat": {"id": chat_id}, "text": marker},
            },
            headers={"X-Telegram-Bot-Api-Secret-Token": secret},
        )
        assert response.status_code == 200
        assert response.json() == {"ok": True}

        event = _latest_webhook_event("Telegram")
        assert event.routed_to_agent == "ceo_agent_chat"

        with get_session() as session:
            messages = session.scalars(
                select(ChatMessage)
                .where(
                    ChatMessage.channel == "Telegram",
                    ChatMessage.external_metadata["chat_key"].astext == chat_id,
                )
                .order_by(ChatMessage.created_at)
            ).all()

        assert len(messages) == 2
        user_message, assistant_message = messages
        assert user_message.role == "user"
        assert user_message.content == marker
        assert user_message.status == "Completed"
        assert assistant_message.role == "assistant"
        assert assistant_message.status == "Pending"
    finally:
        vault.delete_webhook_secret("telegram")
        _cleanup("Telegram", chat_id)


def test_telegram_message_without_text_is_recorded_but_not_routed():
    secret = f"test-secret-{uuid.uuid4()}"
    chat_id = str(uuid.uuid4().int % 1_000_000_000)
    update_id = int(uuid.uuid4().int % 1_000_000_000)
    vault.write_webhook_secret("telegram", {"secret_token": secret})
    try:
        response = client.post(
            "/api/v1/webhooks/telegram",
            json={"update_id": update_id, "message": {"chat": {"id": chat_id}, "sticker": {}}},
            headers={"X-Telegram-Bot-Api-Secret-Token": secret},
        )
        assert response.status_code == 200

        event = _latest_webhook_event("Telegram")
        assert event.routed_to_agent is None

        with get_session() as session:
            count = (
                session.query(ChatMessage)
                .filter(
                    ChatMessage.channel == "Telegram",
                    ChatMessage.external_metadata["chat_key"].astext == chat_id,
                )
                .count()
            )
        assert count == 0
    finally:
        vault.delete_webhook_secret("telegram")


def test_discord_slash_command_returns_deferred_ack_and_creates_a_pending_reply():
    private_key = Ed25519PrivateKey.generate()
    public_key_hex = private_key.public_key().public_bytes_raw().hex()
    vault.write_webhook_secret("discord", {"public_key": public_key_hex})
    channel_id = str(uuid.uuid4().int % 1_000_000_000)
    marker = f"integration-test-{uuid.uuid4()}"
    body = {
        "id": str(uuid.uuid4()),
        "type": 2,
        "channel_id": channel_id,
        "application_id": "test-app-id",
        "token": "test-interaction-token",
        "data": {"name": "ask", "options": [{"name": "message", "value": marker}]},
    }
    timestamp = str(int(time.time()))
    raw_body = json.dumps(body).encode("utf-8")
    signature = private_key.sign(timestamp.encode("utf-8") + raw_body)
    try:
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
        assert response.json() == {"type": 5}

        event = _latest_webhook_event("Discord")
        assert event.routed_to_agent == "ceo_agent_chat"

        with get_session() as session:
            messages = session.scalars(
                select(ChatMessage)
                .where(
                    ChatMessage.channel == "Discord",
                    ChatMessage.external_metadata["chat_key"].astext == channel_id,
                )
                .order_by(ChatMessage.created_at)
            ).all()
        assert len(messages) == 2
        assert messages[0].content == marker
        assert messages[1].status == "Pending"
    finally:
        vault.delete_webhook_secret("discord")
        _cleanup("Discord", channel_id)


def test_discord_non_command_interaction_is_recorded_but_not_routed():
    private_key = Ed25519PrivateKey.generate()
    public_key_hex = private_key.public_key().public_bytes_raw().hex()
    vault.write_webhook_secret("discord", {"public_key": public_key_hex})
    channel_id = str(uuid.uuid4().int % 1_000_000_000)
    body = {
        "id": str(uuid.uuid4()),
        "type": 3,  # MESSAGE_COMPONENT -- a button click, not a slash command
        "channel_id": channel_id,
        "application_id": "test-app-id",
        "token": "test-interaction-token",
        "data": {"custom_id": "some-button"},
    }
    timestamp = str(int(time.time()))
    raw_body = json.dumps(body).encode("utf-8")
    signature = private_key.sign(timestamp.encode("utf-8") + raw_body)
    try:
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
        assert response.json() == {"type": 4, "data": {"content": ""}}

        event = _latest_webhook_event("Discord")
        assert event.routed_to_agent is None
    finally:
        vault.delete_webhook_secret("discord")
