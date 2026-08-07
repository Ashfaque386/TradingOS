"""Real outbound omni-channel dispatch (REL-010 E10.2, REL-026, REL-027, Notification/Omni-
Channel Agent AGT-022).

Telegram, Discord, WhatsApp (REL-026), and Slack (REL-027) all get a real, live outbound send --
FR-10's own literal 4-platform wording, closed for real.

All four functions are plain async `httpx` calls (no SDK) matching every broker adapter's own
established style (`src/brokers/kite_connect_adapter.py`, `upstox_adapter.py`). Real Telegram
Bot API / Discord API / WhatsApp Business Cloud API / Slack Web API endpoints, not guessed --
confirmed against each platform's current docs (WhatsApp's `text` field is a nested
`{"body": ...}` object, not a bare string, and its current API version is v25.0; Slack's Web API
always returns HTTP 200 even on a real failure -- `chat.postMessage`'s own `"ok": false` JSON
field is the real signal, not the HTTP status).
"""

from typing import Any

import httpx

_TELEGRAM_API_BASE = "https://api.telegram.org"
_DISCORD_API_BASE = "https://discord.com/api/v10"
_WHATSAPP_API_BASE = "https://graph.facebook.com/v25.0"
_SLACK_API_BASE = "https://slack.com/api"


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


async def send_slack_message(
    *, channel: str, text: str, bot_token: str, transport: httpx.AsyncBaseTransport | None = None
) -> dict[str, Any]:
    """`POST /chat.postMessage` -- https://docs.slack.dev/reference/methods/chat.postmessage.
    `channel` is the Slack channel ID to post into (the inbound event's own `event.channel`
    field), not the platform name. Slack's Web API is a real, confirmed exception to this
    module's other functions: it always returns HTTP 200, even on failure -- `raise_for_status()`
    alone would never fire for a real bad-token or channel-not-found error, so this explicitly
    checks the response body's own `"ok"` field and raises `RuntimeError` when it's false.
    `transport` is test-only, see `send_telegram_message`."""
    async with httpx.AsyncClient(timeout=10.0, transport=transport) as client:
        response = await client.post(
            f"{_SLACK_API_BASE}/chat.postMessage",
            headers={"Authorization": f"Bearer {bot_token}"},
            json={"channel": channel, "text": text},
        )
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        if not result.get("ok"):
            raise RuntimeError(f"Slack API error: {result.get('error', 'unknown')}")
        return result


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
