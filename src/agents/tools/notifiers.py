"""Real outbound omni-channel dispatch (REL-010 E10.2, REL-026, Notification/Omni-Channel Agent
AGT-022).

Telegram, Discord, and (since REL-026) WhatsApp all get a real, live outbound send.

All three functions are plain async `httpx` calls (no SDK) matching every broker adapter's own
established style (`src/brokers/kite_connect_adapter.py`, `upstox_adapter.py`). Real Telegram
Bot API / Discord API / WhatsApp Business Cloud API endpoints, not guessed -- confirmed against
each platform's current docs (WhatsApp's `text` field is a nested `{"body": ...}` object, not a
bare string, and its current API version is v25.0, verified 2026-08-05 rather than assumed).
"""

from typing import Any

import httpx

_TELEGRAM_API_BASE = "https://api.telegram.org"
_DISCORD_API_BASE = "https://discord.com/api/v10"
_WHATSAPP_API_BASE = "https://graph.facebook.com/v25.0"


async def send_telegram_message(
    *, chat_id: str, text: str, bot_token: str, transport: httpx.AsyncBaseTransport | None = None
) -> dict[str, Any]:
    """`POST /bot{token}/sendMessage` -- https://core.telegram.org/bots/api#sendmessage.
    Raises `httpx.HTTPStatusError` on a real non-2xx response (e.g. bot blocked by the user,
    invalid chat_id) -- the caller is expected to catch this and degrade, not swallow it here.
    `transport` is test-only (real callers never pass it) -- same `httpx.MockTransport` injection
    pattern already used by every broker adapter's own unit tests
    (tests/unit/test_kite_connect_adapter.py), so this never makes a real network call in tests."""
    async with httpx.AsyncClient(timeout=10.0, transport=transport) as client:
        response = await client.post(
            f"{_TELEGRAM_API_BASE}/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
        )
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]


async def send_discord_followup(
    *,
    application_id: str,
    interaction_token: str,
    content: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """`PATCH /webhooks/{application_id}/{interaction_token}/messages/@original` --
    https://discord.com/developers/docs/interactions/receiving-and-responding -- edits in the
    real content after this app already returned a deferred ack (`{"type": 5}`) to the original
    interaction within Discord's real 3-second requirement (src/api/routers/webhooks.py).
    `transport` is test-only, see `send_telegram_message`."""
    async with httpx.AsyncClient(timeout=10.0, transport=transport) as client:
        response = await client.patch(
            f"{_DISCORD_API_BASE}/webhooks/{application_id}/{interaction_token}/messages/@original",
            json={"content": content},
        )
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]


async def send_whatsapp_message(
    *,
    to: str,
    text: str,
    phone_number_id: str,
    access_token: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """`POST /{phone-number-id}/messages` -- WhatsApp Business Cloud API
    (https://developers.facebook.com/docs/whatsapp/cloud-api/reference/messages). `to` is the
    recipient's real WhatsApp phone number (the inbound webhook's own `messages[0].from` field).
    `transport` is test-only, see `send_telegram_message`."""
    async with httpx.AsyncClient(timeout=10.0, transport=transport) as client:
        response = await client.post(
            f"{_WHATSAPP_API_BASE}/{phone_number_id}/messages",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "text",
                "text": {"body": text},
            },
        )
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]
