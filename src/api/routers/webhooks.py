"""Inbound omni-channel webhook gateway (REL-007 E7.7, SEC-025..031): real signature
verification, replay prevention, and rate limiting for each platform.

REL-010 E10.1: Telegram and Discord messages are now actually routed to the CEO Agent (via the
same real, already-tested reply pipeline the in-dashboard chat uses --
src/api/routers/chat.py::generate_and_store_reply) and a real reply is sent back via
`notify_omni_channel` (src/agents/tools/skills.py, REL-010 E10.2). WhatsApp stays
recording-only (`_record_event`) -- not routed this release, per the user's explicit platform
decision, not silently pretended.

No JWT/require_role auth on any route here -- the platform's own signature IS the
authentication. SEC-030's "resolve to an internal TradingOS identity and enforce RBAC" step
remains explicitly out of scope: webhook-originated chat has the same read-mostly-Q&A authority
ceiling the dashboard chat already has (it cannot place trades or call any RBAC-gated endpoint,
since it only ever reaches `ceo_agent_chat`'s free-text prompt, never a mutating tool call).
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
    verify_telegram_secret_token,
    verify_whatsapp_signature,
)
from src.memory.redis_client import get_redis_client
from src.models.chat import ChatMessage
from src.models.webhook import WebhookEvent

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])

_REPLAY_TIMESTAMP_SKEW_SECONDS = 5 * 60  # SEC-029
_ROUTED_TO_AGENT = "ceo_agent_chat"


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
    message_id = (
        body.get("entry", [{}])[0]
        .get("changes", [{}])[0]
        .get("value", {})
        .get("messages", [{}])[0]
        .get("id", "unknown")
    )

    redis_client = get_redis_client()
    if is_replay("whatsapp", str(message_id), redis_client=redis_client):
        return {"ok": True}

    chat_id = str(
        body.get("entry", [{}])[0]
        .get("changes", [{}])[0]
        .get("value", {})
        .get("messages", [{}])[0]
        .get("from", "unknown")
    )
    if not check_rate_limit("whatsapp", chat_id, redis_client=redis_client):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    _record_event("WhatsApp", body)
    return {"ok": True}
