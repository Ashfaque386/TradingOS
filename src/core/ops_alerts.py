"""REL-031 (SEC-040): direct outbound ops alerting for scheduled/background jobs that run outside
Grafana's own alerting pipeline. `scripts/verify_audit_chain.py` is a one-shot script with no
running Prometheus target for Grafana to alert on, so it calls the real Telegram/Discord/Slack
channels REL-029 already wired for downtime alerts (monitoring/grafana/provisioning/alerting/
contact-points.yaml) directly via httpx, rather than through Grafana's contact-point routing.

`src/agents/tools/notifiers.py`'s own `send_slack_message`/`send_discord_followup` are NOT reused
here: those need a Slack bot token + channel ID, or a Discord interaction token -- both
command-response shapes for the Notification/Omni-Channel Agent (AGT-022), not the incoming-
webhook credentials REL-029 already has in .env (`SLACK_WEBHOOK_URL`, `DISCORD_ALERT_WEBHOOK_URL`).
Telegram's real shape is identical either way (bot_token + chat_id + text), so
`send_telegram_message` is reused as-is rather than duplicated.
"""

from __future__ import annotations

import httpx

from src.agents.tools.notifiers import send_telegram_message
from src.core.config import Settings, get_settings

_SEND_TIMEOUT_SECONDS = 10.0


async def send_discord_webhook_alert(
    *, webhook_url: str, content: str, transport: httpx.AsyncBaseTransport | None = None
) -> None:
    """`POST` to a real Discord Incoming Webhook URL --
    https://discord.com/developers/docs/resources/webhook#execute-webhook. `transport` is
    test-only, see `notifiers.send_telegram_message`."""
    async with httpx.AsyncClient(timeout=_SEND_TIMEOUT_SECONDS, transport=transport) as client:
        response = await client.post(webhook_url, json={"content": content})
        response.raise_for_status()


async def send_slack_webhook_alert(
    *, webhook_url: str, text: str, transport: httpx.AsyncBaseTransport | None = None
) -> None:
    """`POST` to a real Slack Incoming Webhook URL -- https://api.slack.com/messaging/webhooks.
    Unlike `chat.postMessage` (notifiers.send_slack_message), a real Incoming Webhook failure DOES
    surface as a non-2xx HTTP status, so `raise_for_status()` alone is a correct real failure
    signal here. `transport` is test-only, see `notifiers.send_telegram_message`."""
    async with httpx.AsyncClient(timeout=_SEND_TIMEOUT_SECONDS, transport=transport) as client:
        response = await client.post(webhook_url, json={"text": text})
        response.raise_for_status()


async def send_ops_alert(
    message: str,
    *,
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[str]:
    """Best-effort fan-out to every configured channel; never raises -- a scheduled job's own
    exit code must reflect the underlying check's real result, not an alert-delivery hiccup.
    Returns the list of channel names that failed to send (empty if all configured channels
    succeeded, or if none are configured at all). `transport` is test-only (forwarded to every
    channel call), see `notifiers.send_telegram_message`."""
    settings = settings or get_settings()
    failures: list[str] = []

    if settings.telegram_alert_bot_token and settings.telegram_alert_chat_id:
        try:
            await send_telegram_message(
                chat_id=settings.telegram_alert_chat_id,
                text=message,
                bot_token=settings.telegram_alert_bot_token,
                transport=transport,
            )
        except Exception:  # noqa: BLE001 -- one channel's failure must not block the others
            failures.append("telegram")

    if settings.discord_alert_webhook_url:
        try:
            await send_discord_webhook_alert(
                webhook_url=settings.discord_alert_webhook_url,
                content=message,
                transport=transport,
            )
        except Exception:  # noqa: BLE001
            failures.append("discord")

    if settings.slack_webhook_url:
        try:
            await send_slack_webhook_alert(
                webhook_url=settings.slack_webhook_url, text=message, transport=transport
            )
        except Exception:  # noqa: BLE001
            failures.append("slack")

    return failures
