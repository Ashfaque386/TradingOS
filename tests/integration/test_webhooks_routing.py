"""REL-010 E10.1 webhook-gateway routing tests against the real FastAPI app + real Postgres/
Redis. Signature verification/replay/rate-limit are already covered by
tests/integration/test_webhooks_api.py (REL-007 E7.7) -- these tests cover the NEW behavior this
epic adds: a real message with text gets routed to the CEO Agent's real reply pipeline.

Deliberately does NOT wait for the real LLM reply to complete, same reasoning as
tests/integration/test_chat_api.py's own docstring (a real reply can take minutes on this host)
-- asserts the real synchronous state (WebhookEvent.routed_to_agent populated, a real
"Pending" ChatMessage pair persisted scoped to this one external chat thread), not the eventual
reply content.

UPDATE 2026-08-01 (REL-014 E14.3, SEC-030): routing now also requires the sender to resolve to a
real, verified NotificationChannel -- every "routes to CEO Agent" test below seeds one via
`_seed_verified_sender()`; the new `test_*_unrecognized_sender_is_recorded_but_not_routed` tests
prove the opposite case (real signature, real text, no matching sender -- not routed).
"""

import hashlib
import hmac
import json
import time
import uuid

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from sqlalchemy import select

from src.api.main import app
from src.core import vault
from src.core.db import get_session
from src.core.security import hash_password
from src.models.chat import ChatMessage
from src.models.user import NotificationChannel, User
from src.models.webhook import WebhookEvent

client = TestClient(app)


def _seed_verified_sender(channel: str, external_handle: str) -> uuid.UUID:
    """SEC-030: creates a real User + a real, verified NotificationChannel binding so a webhook
    sender resolves to a known TradingOS identity -- mirrors the real /settings/notification-
    channels write path, just seeded directly for test speed."""
    user_id = uuid.uuid4()
    with get_session() as session:
        session.add(
            User(
                id=user_id,
                email=f"webhook-sender-{user_id}@example.invalid",
                hashed_password=hash_password("test-password-123"),
                role="ReadOnlyAuditor",
            )
        )
        session.add(
            NotificationChannel(
                user_id=user_id,
                channel_type=channel,
                external_handle=external_handle,
                is_verified=True,
            )
        )
        session.commit()
    return user_id


def _cleanup_sender(user_id: uuid.UUID) -> None:
    with get_session() as session:
        session.query(NotificationChannel).filter(NotificationChannel.user_id == user_id).delete(
            synchronize_session=False
        )
        session.query(User).filter(User.id == user_id).delete(synchronize_session=False)
        session.commit()


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
    sender_id = _seed_verified_sender("Telegram", chat_id)
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
        _cleanup_sender(sender_id)


def test_telegram_unrecognized_sender_is_recorded_but_not_routed():
    """SEC-030: real signature, real text, but no verified NotificationChannel binds this
    chat_id to any TradingOS user -- must be recorded for audit, never routed."""
    secret = f"test-secret-{uuid.uuid4()}"
    chat_id = str(uuid.uuid4().int % 1_000_000_000)  # deliberately never seeded as a sender
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
        assert count == 0, "an unrecognized sender's message must never create a ChatMessage pair"
    finally:
        vault.delete_webhook_secret("telegram")


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
    discord_user_id = str(uuid.uuid4().int % 1_000_000_000)
    marker = f"integration-test-{uuid.uuid4()}"
    body = {
        "id": str(uuid.uuid4()),
        "type": 2,
        "channel_id": channel_id,
        "application_id": "test-app-id",
        "token": "test-interaction-token",
        "member": {"user": {"id": discord_user_id}},
        "data": {"name": "ask", "options": [{"name": "message", "value": marker}]},
    }
    timestamp = str(int(time.time()))
    raw_body = json.dumps(body).encode("utf-8")
    signature = private_key.sign(timestamp.encode("utf-8") + raw_body)
    sender_id = _seed_verified_sender("Discord", discord_user_id)
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
        _cleanup_sender(sender_id)


def test_discord_unrecognized_sender_is_recorded_but_not_routed():
    """SEC-030: real signature, a real slash command, but no verified NotificationChannel binds
    this Discord user ID to any TradingOS user -- must be recorded for audit, never routed."""
    private_key = Ed25519PrivateKey.generate()
    public_key_hex = private_key.public_key().public_bytes_raw().hex()
    vault.write_webhook_secret("discord", {"public_key": public_key_hex})
    channel_id = str(uuid.uuid4().int % 1_000_000_000)
    discord_user_id = str(uuid.uuid4().int % 1_000_000_000)  # deliberately never seeded
    marker = f"integration-test-{uuid.uuid4()}"
    body = {
        "id": str(uuid.uuid4()),
        "type": 2,
        "channel_id": channel_id,
        "application_id": "test-app-id",
        "token": "test-interaction-token",
        "member": {"user": {"id": discord_user_id}},
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
        assert response.json() == {"type": 4, "data": {"content": ""}}

        event = _latest_webhook_event("Discord")
        assert event.routed_to_agent is None

        with get_session() as session:
            count = (
                session.query(ChatMessage)
                .filter(
                    ChatMessage.channel == "Discord",
                    ChatMessage.external_metadata["chat_key"].astext == channel_id,
                )
                .count()
            )
        assert count == 0, "an unrecognized sender's message must never create a ChatMessage pair"
    finally:
        vault.delete_webhook_secret("discord")


def _whatsapp_signature(app_secret: str, raw_body: bytes) -> str:
    return hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


def test_whatsapp_message_with_text_routes_to_ceo_agent_and_creates_a_pending_reply():
    """REL-026: mirrors the Telegram test above -- WhatsApp's inbound receiver (signature
    verification, replay/rate-limit checks) has been real since REL-007; this proves the
    routing half, previously missing, now works the same way."""
    app_secret = f"test-app-secret-{uuid.uuid4()}"
    chat_id = str(uuid.uuid4().int % 1_000_000_000)
    message_id = f"wamid.{uuid.uuid4()}"
    marker = f"integration-test-{uuid.uuid4()}"
    vault.write_webhook_secret("whatsapp", {"app_secret": app_secret})
    sender_id = _seed_verified_sender("WhatsApp", chat_id)
    try:
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {"id": message_id, "from": chat_id, "text": {"body": marker}}
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        raw_body = json.dumps(payload).encode("utf-8")
        signature = _whatsapp_signature(app_secret, raw_body)

        response = client.post(
            "/api/v1/webhooks/whatsapp",
            content=raw_body,
            headers={
                "X-Hub-Signature-256": f"sha256={signature}",
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 200
        assert response.json() == {"ok": True}

        event = _latest_webhook_event("WhatsApp")
        assert event.routed_to_agent == "ceo_agent_chat"

        with get_session() as session:
            messages = session.scalars(
                select(ChatMessage)
                .where(
                    ChatMessage.channel == "WhatsApp",
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
        vault.delete_webhook_secret("whatsapp")
        _cleanup("WhatsApp", chat_id)
        _cleanup_sender(sender_id)


def test_whatsapp_unrecognized_sender_is_recorded_but_not_routed():
    """SEC-030: real signature, real text, but no verified NotificationChannel binds this
    chat_id to any TradingOS user -- must be recorded for audit, never routed."""
    app_secret = f"test-app-secret-{uuid.uuid4()}"
    chat_id = str(uuid.uuid4().int % 1_000_000_000)  # deliberately never seeded as a sender
    message_id = f"wamid.{uuid.uuid4()}"
    marker = f"integration-test-{uuid.uuid4()}"
    vault.write_webhook_secret("whatsapp", {"app_secret": app_secret})
    try:
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {"id": message_id, "from": chat_id, "text": {"body": marker}}
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        raw_body = json.dumps(payload).encode("utf-8")
        signature = _whatsapp_signature(app_secret, raw_body)

        response = client.post(
            "/api/v1/webhooks/whatsapp",
            content=raw_body,
            headers={
                "X-Hub-Signature-256": f"sha256={signature}",
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 200
        assert response.json() == {"ok": True}

        event = _latest_webhook_event("WhatsApp")
        assert event.routed_to_agent is None

        with get_session() as session:
            count = (
                session.query(ChatMessage)
                .filter(
                    ChatMessage.channel == "WhatsApp",
                    ChatMessage.external_metadata["chat_key"].astext == chat_id,
                )
                .count()
            )
        assert count == 0, "an unrecognized sender's message must never create a ChatMessage pair"
    finally:
        vault.delete_webhook_secret("whatsapp")


def test_whatsapp_message_without_text_is_recorded_but_not_routed():
    app_secret = f"test-app-secret-{uuid.uuid4()}"
    chat_id = str(uuid.uuid4().int % 1_000_000_000)
    message_id = f"wamid.{uuid.uuid4()}"
    vault.write_webhook_secret("whatsapp", {"app_secret": app_secret})
    try:
        # A real WhatsApp image/media message has no "text" field at all.
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "id": message_id,
                                        "from": chat_id,
                                        "type": "image",
                                        "image": {"id": "media-1"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        raw_body = json.dumps(payload).encode("utf-8")
        signature = _whatsapp_signature(app_secret, raw_body)

        response = client.post(
            "/api/v1/webhooks/whatsapp",
            content=raw_body,
            headers={
                "X-Hub-Signature-256": f"sha256={signature}",
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 200

        event = _latest_webhook_event("WhatsApp")
        assert event.routed_to_agent is None

        with get_session() as session:
            count = (
                session.query(ChatMessage)
                .filter(
                    ChatMessage.channel == "WhatsApp",
                    ChatMessage.external_metadata["chat_key"].astext == chat_id,
                )
                .count()
            )
        assert count == 0
    finally:
        vault.delete_webhook_secret("whatsapp")


def _slack_signature_headers(signing_secret: str, raw_body: bytes) -> dict[str, str]:
    timestamp = str(int(time.time()))
    base_string = f"v0:{timestamp}:".encode() + raw_body
    signature = (
        "v0=" + hmac.new(signing_secret.encode("utf-8"), base_string, hashlib.sha256).hexdigest()
    )
    return {
        "X-Slack-Signature": signature,
        "X-Slack-Request-Timestamp": timestamp,
        "Content-Type": "application/json",
    }


def test_slack_message_with_text_routes_to_ceo_agent_and_creates_a_pending_reply():
    """REL-027: mirrors the Telegram test above -- Slack is real from scratch this release, no
    prior inbound handling of any kind existed."""
    signing_secret = f"test-signing-secret-{uuid.uuid4()}"
    channel_id = f"C{uuid.uuid4().hex[:10]}"
    slack_user_id = f"U{uuid.uuid4().hex[:10]}"
    marker = f"integration-test-{uuid.uuid4()}"
    vault.write_webhook_secret("slack", {"signing_secret": signing_secret})
    sender_id = _seed_verified_sender("Slack", slack_user_id)
    try:
        payload = {
            "type": "event_callback",
            "event_id": f"Ev{uuid.uuid4().hex[:12]}",
            "event": {
                "type": "message",
                "channel": channel_id,
                "user": slack_user_id,
                "text": marker,
            },
        }
        raw_body = json.dumps(payload).encode("utf-8")

        response = client.post(
            "/api/v1/webhooks/slack",
            content=raw_body,
            headers=_slack_signature_headers(signing_secret, raw_body),
        )
        assert response.status_code == 200
        assert response.json() == {"ok": True}

        event = _latest_webhook_event("Slack")
        assert event.routed_to_agent == "ceo_agent_chat"

        with get_session() as session:
            messages = session.scalars(
                select(ChatMessage)
                .where(
                    ChatMessage.channel == "Slack",
                    ChatMessage.external_metadata["chat_key"].astext == channel_id,
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
        vault.delete_webhook_secret("slack")
        _cleanup("Slack", channel_id)
        _cleanup_sender(sender_id)


def test_slack_unrecognized_sender_is_recorded_but_not_routed():
    """SEC-030: real signature, real text, but no verified NotificationChannel binds this
    Slack user ID to any TradingOS user -- must be recorded for audit, never routed."""
    signing_secret = f"test-signing-secret-{uuid.uuid4()}"
    channel_id = f"C{uuid.uuid4().hex[:10]}"
    slack_user_id = f"U{uuid.uuid4().hex[:10]}"  # deliberately never seeded
    marker = f"integration-test-{uuid.uuid4()}"
    vault.write_webhook_secret("slack", {"signing_secret": signing_secret})
    try:
        payload = {
            "type": "event_callback",
            "event_id": f"Ev{uuid.uuid4().hex[:12]}",
            "event": {
                "type": "message",
                "channel": channel_id,
                "user": slack_user_id,
                "text": marker,
            },
        }
        raw_body = json.dumps(payload).encode("utf-8")

        response = client.post(
            "/api/v1/webhooks/slack",
            content=raw_body,
            headers=_slack_signature_headers(signing_secret, raw_body),
        )
        assert response.status_code == 200
        assert response.json() == {"ok": True}

        event = _latest_webhook_event("Slack")
        assert event.routed_to_agent is None

        with get_session() as session:
            count = (
                session.query(ChatMessage)
                .filter(
                    ChatMessage.channel == "Slack",
                    ChatMessage.external_metadata["chat_key"].astext == channel_id,
                )
                .count()
            )
        assert count == 0, "an unrecognized sender's message must never create a ChatMessage pair"
    finally:
        vault.delete_webhook_secret("slack")


def test_slack_message_without_text_is_recorded_but_not_routed():
    signing_secret = f"test-signing-secret-{uuid.uuid4()}"
    channel_id = f"C{uuid.uuid4().hex[:10]}"
    slack_user_id = f"U{uuid.uuid4().hex[:10]}"
    vault.write_webhook_secret("slack", {"signing_secret": signing_secret})
    try:
        # A real file-share event has no "text" field.
        payload = {
            "type": "event_callback",
            "event_id": f"Ev{uuid.uuid4().hex[:12]}",
            "event": {"type": "message", "channel": channel_id, "user": slack_user_id},
        }
        raw_body = json.dumps(payload).encode("utf-8")

        response = client.post(
            "/api/v1/webhooks/slack",
            content=raw_body,
            headers=_slack_signature_headers(signing_secret, raw_body),
        )
        assert response.status_code == 200

        event = _latest_webhook_event("Slack")
        assert event.routed_to_agent is None

        with get_session() as session:
            count = (
                session.query(ChatMessage)
                .filter(
                    ChatMessage.channel == "Slack",
                    ChatMessage.external_metadata["chat_key"].astext == channel_id,
                )
                .count()
            )
        assert count == 0
    finally:
        vault.delete_webhook_secret("slack")


def test_slack_bot_authored_message_is_recorded_but_not_routed():
    """REL-027: Slack delivers every channel message, including this app's own real replies, to
    every subscribed app -- a real bot_id on the event means it must never be routed back to the
    CEO Agent, or a real infinite reply loop would result."""
    signing_secret = f"test-signing-secret-{uuid.uuid4()}"
    channel_id = f"C{uuid.uuid4().hex[:10]}"
    marker = f"integration-test-{uuid.uuid4()}"
    vault.write_webhook_secret("slack", {"signing_secret": signing_secret})
    try:
        payload = {
            "type": "event_callback",
            "event_id": f"Ev{uuid.uuid4().hex[:12]}",
            "event": {
                "type": "message",
                "channel": channel_id,
                "text": marker,
                "bot_id": "B0REALBOTID",
            },
        }
        raw_body = json.dumps(payload).encode("utf-8")

        response = client.post(
            "/api/v1/webhooks/slack",
            content=raw_body,
            headers=_slack_signature_headers(signing_secret, raw_body),
        )
        assert response.status_code == 200

        event = _latest_webhook_event("Slack")
        assert event.routed_to_agent is None

        with get_session() as session:
            count = (
                session.query(ChatMessage)
                .filter(
                    ChatMessage.channel == "Slack",
                    ChatMessage.external_metadata["chat_key"].astext == channel_id,
                )
                .count()
            )
        assert count == 0
    finally:
        vault.delete_webhook_secret("slack")


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
