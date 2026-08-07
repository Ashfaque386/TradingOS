"""Inbound omni-channel webhook gateway (REL-007 E7.7 SEC-025..031, REL-027 SEC-047): real
signature verification, replay prevention, and rate limiting for each platform.

REL-010 E10.1: Telegram and Discord messages are now actually routed to the CEO Agent (via the
same real, already-tested reply pipeline the in-dashboard chat uses --
src/api/routers/chat.py::generate_and_store_reply) and a real reply is sent back via
`notify_omni_channel` (src/agents/tools/skills.py, REL-010 E10.2). REL-026: WhatsApp now routes
the exact same way -- the inbound receiver's real Meta webhook verification handshake, real
signature verification, and real replay/rate-limit checks were already fully real since REL-007;
only the routing/reply half was ever missing. REL-027: Slack is real from scratch (no prior
config/route/notifier existed at all, confirmed via a full-repo grep before building this) --
its own `POST /slack` handler additionally handles the one-time Events API `url_verification`
handshake, and filters out any event carrying a real `bot_id` (Slack delivers every channel
message, including this app's own replies, to every subscribed app -- routing a bot's own reply
back to itself would create a real infinite loop).

No JWT/require_role auth on any route here -- the platform's own signature IS the
authentication for "this really came from Telegram/Discord". UPDATE 2026-08-01 (REL-014 E14.3,
SEC-030): the sender-identity step described above -- "even after signature verification
confirms the message truly came from Telegram/Discord, the gateway still resolves the sending
platform-user-ID to an internal TradingOS identity ... a verified message from an unrecognized
or under-privileged chat user is rejected before reaching the CEO Agent" -- was deferred twice
(REL-007, REL-010) and is now real: `_resolve_sender()` below looks up the inbound chat/user ID
against `NOTIFICATION_CHANNELS` (DB-002, the same table `/settings/notification-channels`
already writes), and a sender with no verified channel row is recorded (for audit) but never
routed to the CEO Agent. The read-mostly-Q&A authority ceiling this docstring used to cite as
"why this is low-risk anyway" is unchanged and still true -- this closes the identity gap on top
of that, not instead of it.
"""

import threading
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response
from sqlalchemy import select

from src.agents.tools.registry import get_skill_registry
from src.agents.tools.skills import SkillNotImplementedError
from src.api.routers.chat import generate_and_store_reply
from src.core import vault
from src.core.config import get_settings
from src.core.db import get_session
from src.core.webhook_rate_limit import check_rate_limit
from src.core.webhook_replay import is_replay
from src.core.webhook_security import (
    verify_discord_signature,
    verify_slack_signature,
    verify_telegram_secret_token,
    verify_whatsapp_signature,
)
from src.memory.redis_client import get_redis_client
from src.models.chat import ChatMessage
from src.models.user import NotificationChannel, User
from src.models.webhook import WebhookEvent

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])

_REPLAY_TIMESTAMP_SKEW_SECONDS = 5 * 60  # SEC-029
_ROUTED_TO_AGENT = "ceo_agent_chat"


def _resolve_sender(channel: str, external_handle: str) -> User | None:
    """SEC-030: resolves a verified platform sender to an internal TradingOS identity. Returns
    None for any sender with no matching, verified `NotificationChannel` row -- an unrecognized
    or unverified sender, even one whose message passed real signature verification, is not a
    known TradingOS user and must not reach the CEO Agent."""
    with get_session() as session:
        binding = session.scalars(
            select(NotificationChannel).where(
                NotificationChannel.channel_type == channel,
                NotificationChannel.external_handle == external_handle,
                NotificationChannel.is_verified.is_(True),
            )
        ).first()
        if binding is None:
            return None
        user = session.get(User, binding.user_id)
        if user is None or not user.is_active:
            return None
        session.expunge(user)
        return user


def _record_event(channel: str, raw_body: dict[str, Any]) -> uuid.UUID:
    with get_session() as session:
        event = WebhookEvent(
            channel=channel,
            user_message_raw=raw_body,
            normalized_payload=raw_body,
            received_at=datetime.now(UTC),
        )
        session.add(event)
        session.commit()
        return event.id


def _mark_event_routed(event_id: uuid.UUID) -> None:
    with get_session() as session:
        event = session.get(WebhookEvent, event_id)
        if event is not None:
            event.routed_to_agent = _ROUTED_TO_AGENT
            session.commit()


def _mark_event_response_sent(event_id: uuid.UUID, reply: str) -> None:
    with get_session() as session:
        event = session.get(WebhookEvent, event_id)
        if event is not None:
            event.response_sent = reply[:500]  # WebhookEvent.response_sent has no length cap
            # in the model, but this table's own docstring calls it "operational debugging, not
            # a system of record" -- a real, bounded excerpt is enough for that purpose.
            session.commit()


def _record_event_and_route(
    *,
    channel: str,
    raw_body: dict[str, Any],
    external_chat_key: str,
    user_text: str,
    external_metadata: dict[str, Any],
    notify_kwargs: dict[str, Any],
) -> uuid.UUID:
    """Shared by the Telegram and Discord handlers (REL-010 E10.1). Mirrors
    src/api/routers/chat.py::send_message's own save-user-row/save-pending-row/dispatch-thread
    sequence exactly, scoped to this one external chat thread (`external_chat_key`) so a
    Telegram user's history never leaks into another Telegram user's or the dashboard's context.
    """
    event_id = _record_event(channel, raw_body)
    _mark_event_routed(event_id)

    with get_session() as session:
        history = [
            (m.role, m.content, m.status)
            for m in session.scalars(
                select(ChatMessage)
                .where(
                    ChatMessage.channel == channel,
                    ChatMessage.external_metadata["chat_key"].astext == external_chat_key,
                )
                .order_by(ChatMessage.created_at)
            )
        ]

        user_message = ChatMessage(
            role="user",
            content=user_text,
            status="Completed",
            channel=channel,
            external_metadata={"chat_key": external_chat_key, **external_metadata},
            webhook_event_id=event_id,
        )
        session.add(user_message)
        session.flush()

        assistant_message = ChatMessage(
            role="assistant",
            content="",
            status="Pending",
            channel=channel,
            external_metadata={"chat_key": external_chat_key, **external_metadata},
            webhook_event_id=event_id,
        )
        session.add(assistant_message)
        session.commit()
        assistant_id = assistant_message.id

    def _on_complete(reply: str, status: str) -> None:
        if status != "Completed" or not reply:
            return
        try:
            get_skill_registry().execute("notify_omni_channel", text=reply, **notify_kwargs)
        except SkillNotImplementedError:
            return  # real, documented gap (e.g. no bot token configured) -- not a bug to raise on
        except Exception:  # noqa: BLE001 -- a delivery failure must never crash this thread
            return
        _mark_event_response_sent(event_id, reply)

    threading.Thread(
        target=generate_and_store_reply,
        kwargs={
            "assistant_message_id": assistant_id,
            "history": history,
            "user_content": user_text,
            "on_complete": _on_complete,
        },
        daemon=True,
    ).start()
    return event_id


@router.post("/telegram")
async def telegram_webhook(request: Request) -> dict[str, bool]:
    settings = get_settings()
    stored = vault.read_webhook_secret("telegram")
    expected_secret = (stored or {}).get("secret_token") or settings.telegram_webhook_secret
    if not expected_secret:
        raise HTTPException(status_code=503, detail="Telegram webhook secret not configured")

    header_value = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if not verify_telegram_secret_token(header_value, expected_secret=expected_secret):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    body = await request.json()
    update_id = body.get("update_id")
    if update_id is None:
        raise HTTPException(status_code=400, detail="Missing update_id")

    redis_client = get_redis_client()
    if is_replay("telegram", str(update_id), redis_client=redis_client):
        return {"ok": True}  # idempotent no-op, per SEC-029 -- not an error

    chat_id = str(body.get("message", {}).get("chat", {}).get("id", "unknown"))
    if not check_rate_limit("telegram", chat_id, redis_client=redis_client):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    text = body.get("message", {}).get("text")
    if not text:
        # A real Telegram update with no text (a sticker, a photo caption-less message, a
        # /start with no further message, etc.) -- still recorded for real, just not routed to
        # an agent that has nothing to answer.
        _record_event("Telegram", body)
        return {"ok": True}

    if _resolve_sender("Telegram", chat_id) is None:
        # SEC-030: a real, signature-verified Telegram message, but from a chat ID with no
        # verified NotificationChannel binding -- recorded for audit, never routed to the CEO
        # Agent. Acks normally rather than erroring, matching Telegram's own expectation that a
        # webhook always returns 200 regardless of what the bot chose to do with the update.
        _record_event("Telegram", body)
        return {"ok": True}

    _record_event_and_route(
        channel="Telegram",
        raw_body=body,
        external_chat_key=chat_id,
        user_text=text,
        external_metadata={"chat_id": chat_id},
        notify_kwargs={"channel": "telegram", "chat_id": chat_id},
    )
    return {"ok": True}


@router.post("/discord")
async def discord_webhook(request: Request) -> dict[str, Any]:
    settings = get_settings()
    stored = vault.read_webhook_secret("discord")
    public_key_hex = (stored or {}).get("public_key") or settings.discord_public_key
    if not public_key_hex:
        raise HTTPException(status_code=503, detail="Discord public key not configured")

    raw_body = await request.body()
    signature_hex = request.headers.get("X-Signature-Ed25519")
    timestamp = request.headers.get("X-Signature-Timestamp")
    if not verify_discord_signature(
        raw_body, signature_hex, timestamp, public_key_hex=public_key_hex
    ):
        raise HTTPException(status_code=401, detail="Invalid request signature")
    assert timestamp is not None  # verify_discord_signature above already rejected a None one

    body = await request.json()
    if body.get("type") == 1:
        # Discord's PING handshake, sent once when the webhook URL is registered -- must be
        # echoed back verbatim, real behavior genuinely testable with a synthetic keypair.
        return {"type": 1}

    if abs(time.time() - float(timestamp)) > _REPLAY_TIMESTAMP_SKEW_SECONDS:
        raise HTTPException(status_code=401, detail="Timestamp outside allowed skew")

    interaction_id = body.get("id", "unknown")
    redis_client = get_redis_client()
    if is_replay("discord", str(interaction_id), redis_client=redis_client):
        return {"type": 4, "data": {"content": ""}}

    channel_id = str(body.get("channel_id", "unknown"))
    if not check_rate_limit("discord", channel_id, redis_client=redis_client):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    # type 2 = APPLICATION_COMMAND (a real slash command, e.g. `/ask message:<text>`) -- the
    # only interaction type this gateway actually routes to the CEO Agent. Anything else (a
    # message component click, a context-menu command) is recorded but not routed, same as
    # before this epic.
    text = None
    if body.get("type") == 2:
        options = body.get("data", {}).get("options", [])
        text = next((opt["value"] for opt in options if opt.get("name") == "message"), None)

    if not text:
        _record_event("Discord", body)
        return {"type": 4, "data": {"content": ""}}

    # The interacting Discord USER's ID -- distinct from `channel_id` above (which scopes rate
    # limiting to the channel, not the person). `member.user.id` for a guild-context interaction,
    # `user.id` for a DM-context one; Discord sends exactly one of the two per its own API shape.
    discord_user_id = str(
        body.get("member", {}).get("user", {}).get("id")
        or body.get("user", {}).get("id", "unknown")
    )
    if _resolve_sender("Discord", discord_user_id) is None:
        # SEC-030: see the Telegram handler's matching check above.
        _record_event("Discord", body)
        return {"type": 4, "data": {"content": ""}}

    application_id = body.get("application_id", "")
    interaction_token = body.get("token", "")
    _record_event_and_route(
        channel="Discord",
        raw_body=body,
        external_chat_key=channel_id,
        user_text=text,
        external_metadata={
            "channel_id": channel_id,
            "application_id": application_id,
            "interaction_token": interaction_token,
        },
        notify_kwargs={
            "channel": "discord",
            "application_id": application_id,
            "interaction_token": interaction_token,
        },
    )
    # DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE -- Discord requires an ack within 3 seconds; the real
    # LLM call (which can take minutes on this host, see chat.py's own docstring) happens in the
    # background thread _record_event_and_route already started, followed by a real PATCH to
    # this interaction's own follow-up webhook URL once it completes.
    return {"type": 5}


@router.get("/whatsapp")
def whatsapp_verify(
    hub_mode: str = Query(..., alias="hub.mode"),
    hub_verify_token: str = Query(..., alias="hub.verify_token"),
    hub_challenge: str = Query(..., alias="hub.challenge"),
) -> Response:
    """Meta's webhook verification handshake, sent once when the URL is registered."""
    settings = get_settings()
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_verify_token:
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verification token mismatch")


@router.post("/whatsapp")
async def whatsapp_webhook(request: Request) -> dict[str, bool]:
    settings = get_settings()
    stored = vault.read_webhook_secret("whatsapp")
    app_secret = (stored or {}).get("app_secret") or settings.whatsapp_app_secret
    if not app_secret:
        raise HTTPException(status_code=503, detail="WhatsApp app secret not configured")

    raw_body = await request.body()
    signature_header = request.headers.get("X-Hub-Signature-256")
    if not verify_whatsapp_signature(raw_body, signature_header, app_secret=app_secret):
        raise HTTPException(status_code=401, detail="Invalid request signature")

    body = await request.json()
    # REL-026: extracted once (was repeated inline 2x before this release, for message_id/
    # chat_id only -- now also needs the message text, so pulled out to avoid a 3rd repetition
    # of this same nested-dict chain).
    message = (
        body.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {}).get("messages", [{}])[0]
    )
    message_id = message.get("id", "unknown")

    redis_client = get_redis_client()
    if is_replay("whatsapp", str(message_id), redis_client=redis_client):
        return {"ok": True}

    chat_id = str(message.get("from", "unknown"))
    if not check_rate_limit("whatsapp", chat_id, redis_client=redis_client):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    text = message.get("text", {}).get("body")
    if not text:
        # A real WhatsApp message with no text body (an image, a reaction, a status update,
        # etc.) -- still recorded for real, just not routed to an agent that has nothing to
        # answer. Same convention as the Telegram handler above.
        _record_event("WhatsApp", body)
        return {"ok": True}

    if _resolve_sender("WhatsApp", chat_id) is None:
        # SEC-030: see the Telegram handler's matching check above.
        _record_event("WhatsApp", body)
        return {"ok": True}

    _record_event_and_route(
        channel="WhatsApp",
        raw_body=body,
        external_chat_key=chat_id,
        user_text=text,
        external_metadata={"chat_id": chat_id},
        notify_kwargs={"channel": "whatsapp", "to": chat_id},
    )
    return {"ok": True}


@router.post("/slack")
async def slack_webhook(request: Request) -> dict[str, Any]:
    settings = get_settings()
    stored = vault.read_webhook_secret("slack")
    signing_secret = (stored or {}).get("signing_secret") or settings.slack_signing_secret
    if not signing_secret:
        raise HTTPException(status_code=503, detail="Slack signing secret not configured")

    raw_body = await request.body()
    signature_header = request.headers.get("X-Slack-Signature")
    timestamp = request.headers.get("X-Slack-Request-Timestamp")
    if not verify_slack_signature(
        raw_body, signature_header, timestamp, signing_secret=signing_secret
    ):
        raise HTTPException(status_code=401, detail="Invalid request signature")
    assert timestamp is not None  # verify_slack_signature above already rejected a None one

    if abs(time.time() - float(timestamp)) > _REPLAY_TIMESTAMP_SKEW_SECONDS:
        raise HTTPException(status_code=401, detail="Timestamp outside allowed skew")

    body = await request.json()
    if body.get("type") == "url_verification":
        # Slack's one-time Events API registration handshake -- must echo the real challenge
        # value back verbatim, only after real signature verification above ("verify the
        # request's authenticity" is Slack's own documented requirement before responding).
        return {"challenge": body.get("challenge", "")}

    event = body.get("event", {})
    event_id = body.get("event_id", "unknown")

    redis_client = get_redis_client()
    if is_replay("slack", str(event_id), redis_client=redis_client):
        return {"ok": True}

    channel_id = str(event.get("channel", "unknown"))
    if not check_rate_limit("slack", channel_id, redis_client=redis_client):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    if event.get("type") != "message" or event.get("bot_id"):
        # A non-message event (e.g. a reaction), or a message carrying a real bot_id -- Slack
        # delivers every channel message, including this app's own replies, to every subscribed
        # app. Routing a bot-authored message (ours or another app's) back to the CEO Agent would
        # both be nonsensical and, for our own replies specifically, a real infinite loop.
        _record_event("Slack", body)
        return {"ok": True}

    text = event.get("text")
    if not text:
        # A real Slack message with no text (a file upload, an emoji-only reaction message,
        # etc.) -- still recorded for real, just not routed. Same convention as Telegram above.
        _record_event("Slack", body)
        return {"ok": True}

    slack_user_id = str(event.get("user", "unknown"))
    if _resolve_sender("Slack", slack_user_id) is None:
        # SEC-030: see the Telegram handler's matching check above.
        _record_event("Slack", body)
        return {"ok": True}

    _record_event_and_route(
        channel="Slack",
        raw_body=body,
        external_chat_key=channel_id,
        user_text=text,
        external_metadata={"channel_id": channel_id, "slack_user_id": slack_user_id},
        notify_kwargs={"channel": "slack", "channel_id": channel_id},
    )
    return {"ok": True}
