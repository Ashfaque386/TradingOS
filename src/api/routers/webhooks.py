"""Inbound omni-channel webhook gateway (REL-007 E7.7, SEC-025..031): real signature
verification, replay prevention, and rate limiting for each platform. Deliberately minimal
beyond that -- normalizing a verified payload into a `WebhookEvent` row here so the crypto
primitives (src/core/webhook_security.py) get exercised over a real HTTP round-trip, not just
unit-tested in isolation, but actual message-to-agent routing is REL-010's job (it should import
these primitives, not re-implement them).

No JWT/require_role auth on any route here -- the platform's own signature IS the
authentication. SEC-030's "resolve to an internal TradingOS identity and enforce RBAC" step is
explicitly out of scope: no chat-to-TradingOS-identity mapping exists anywhere in this codebase
yet (that's REL-010's job too).
"""

import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response

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
from src.models.webhook import WebhookEvent

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])

_REPLAY_TIMESTAMP_SKEW_SECONDS = 5 * 60  # SEC-029


def _record_event(channel: str, raw_body: dict[str, Any]) -> None:
    with get_session() as session:
        session.add(
            WebhookEvent(
                channel=channel,
                user_message_raw=raw_body,
                normalized_payload=raw_body,
                received_at=datetime.now(UTC),
            )
        )
        session.commit()


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

    _record_event("Telegram", body)
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

    chat_id = str(body.get("channel_id", "unknown"))
    if not check_rate_limit("discord", chat_id, redis_client=redis_client):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    _record_event("Discord", body)
    return {"type": 4, "data": {"content": ""}}


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
