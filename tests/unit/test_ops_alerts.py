"""REL-031 (SEC-040): every call mocked via `httpx.MockTransport`, same convention as
tests/unit/test_notifiers.py -- must NEVER make a real network call.
"""

import httpx
import pytest

from src.core.config import Settings
from src.core.ops_alerts import send_discord_webhook_alert, send_ops_alert, send_slack_webhook_alert


@pytest.mark.asyncio
async def test_send_discord_webhook_alert_posts_the_real_incoming_webhook_shape():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["body"] = request.content
        return httpx.Response(204)

    await send_discord_webhook_alert(
        webhook_url="https://discord.com/api/webhooks/1/abc",
        content="chain broken",
        transport=httpx.MockTransport(handler),
    )

    assert captured["method"] == "POST"
    assert captured["url"] == "https://discord.com/api/webhooks/1/abc"
    assert b'"content":"chain broken"' in captured["body"]


@pytest.mark.asyncio
async def test_send_discord_webhook_alert_raises_on_real_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Unknown Webhook"})

    with pytest.raises(httpx.HTTPStatusError):
        await send_discord_webhook_alert(
            webhook_url="https://discord.com/api/webhooks/1/abc",
            content="chain broken",
            transport=httpx.MockTransport(handler),
        )


@pytest.mark.asyncio
async def test_send_slack_webhook_alert_posts_the_real_incoming_webhook_shape():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["body"] = request.content
        return httpx.Response(200, text="ok")

    await send_slack_webhook_alert(
        webhook_url="https://hooks.slack.com/services/T1/B1/xyz",
        text="chain broken",
        transport=httpx.MockTransport(handler),
    )

    assert captured["method"] == "POST"
    assert captured["url"] == "https://hooks.slack.com/services/T1/B1/xyz"
    assert b'"text":"chain broken"' in captured["body"]


@pytest.mark.asyncio
async def test_send_slack_webhook_alert_raises_on_real_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal_error")

    with pytest.raises(httpx.HTTPStatusError):
        await send_slack_webhook_alert(
            webhook_url="https://hooks.slack.com/services/T1/B1/xyz",
            text="chain broken",
            transport=httpx.MockTransport(handler),
        )


@pytest.mark.asyncio
async def test_send_ops_alert_fans_out_to_every_configured_channel():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "telegram" in str(request.url):
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(200, text="ok")

    settings = Settings(
        telegram_alert_bot_token="tok",
        telegram_alert_chat_id="chat-1",
        discord_alert_webhook_url="https://discord.com/api/webhooks/1/abc",
        slack_webhook_url="https://hooks.slack.com/services/T1/B1/xyz",
    )

    failures = await send_ops_alert(
        "chain broken", settings=settings, transport=httpx.MockTransport(handler)
    )

    assert failures == []
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_send_ops_alert_skips_unconfigured_channels():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"ok": True})

    settings = Settings(
        telegram_alert_bot_token="tok",
        telegram_alert_chat_id="chat-1",
        discord_alert_webhook_url=None,
        slack_webhook_url=None,
    )

    failures = await send_ops_alert(
        "chain broken", settings=settings, transport=httpx.MockTransport(handler)
    )

    assert failures == []
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_send_ops_alert_reports_a_failing_channel_without_raising_or_blocking_the_others():
    def handler(request: httpx.Request) -> httpx.Response:
        if "telegram" in str(request.url):
            return httpx.Response(403, json={"ok": False, "description": "blocked"})
        return httpx.Response(200, json={"ok": True})

    settings = Settings(
        telegram_alert_bot_token="tok",
        telegram_alert_chat_id="chat-1",
        discord_alert_webhook_url="https://discord.com/api/webhooks/1/abc",
        slack_webhook_url="https://hooks.slack.com/services/T1/B1/xyz",
    )

    failures = await send_ops_alert(
        "chain broken", settings=settings, transport=httpx.MockTransport(handler)
    )

    assert failures == ["telegram"]


@pytest.mark.asyncio
async def test_send_ops_alert_returns_empty_when_nothing_is_configured():
    settings = Settings(
        telegram_alert_bot_token=None,
        telegram_alert_chat_id=None,
        discord_alert_webhook_url=None,
        slack_webhook_url=None,
    )

    failures = await send_ops_alert("chain broken", settings=settings)

    assert failures == []
