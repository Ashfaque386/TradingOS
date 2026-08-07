"""REL-010 E10.2: every call mocked via `httpx.MockTransport` -- must NEVER make a real network
call, same convention as tests/unit/test_kite_connect_adapter.py.
"""

import httpx
import pytest

from src.agents.tools.notifiers import (
    send_discord_followup,
    send_slack_message,
    send_telegram_message,
)


@pytest.mark.asyncio
async def test_send_telegram_message_posts_the_real_bot_api_shape():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["body"] = request.content
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})

    result = await send_telegram_message(
        chat_id="123456",
        text="hello from TradingOS",
        bot_token="test-bot-token",
        transport=httpx.MockTransport(handler),
    )

    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.telegram.org/bottest-bot-token/sendMessage"
    assert b'"chat_id":"123456"' in captured["body"]
    assert b'"text":"hello from TradingOS"' in captured["body"]
    assert result == {"ok": True, "result": {"message_id": 42}}


@pytest.mark.asyncio
async def test_send_telegram_message_raises_on_real_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"ok": False, "description": "bot was blocked by the user"})

    with pytest.raises(httpx.HTTPStatusError):
        await send_telegram_message(
            chat_id="123456",
            text="hello",
            bot_token="test-bot-token",
            transport=httpx.MockTransport(handler),
        )


@pytest.mark.asyncio
async def test_send_discord_followup_patches_the_real_webhook_edit_url():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["body"] = request.content
        return httpx.Response(200, json={"id": "msg-1", "content": "hi"})

    result = await send_discord_followup(
        application_id="app-1",
        interaction_token="token-abc",
        content="hi",
        transport=httpx.MockTransport(handler),
    )

    assert captured["method"] == "PATCH"
    assert (
        captured["url"] == "https://discord.com/api/v10/webhooks/app-1/token-abc/messages/@original"
    )
    assert b'"content":"hi"' in captured["body"]
    assert result == {"id": "msg-1", "content": "hi"}


@pytest.mark.asyncio
async def test_send_discord_followup_raises_on_real_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Unknown Webhook"})

    with pytest.raises(httpx.HTTPStatusError):
        await send_discord_followup(
            application_id="app-1",
            interaction_token="token-abc",
            content="hi",
            transport=httpx.MockTransport(handler),
        )


@pytest.mark.asyncio
async def test_send_slack_message_posts_the_real_web_api_shape():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = request.content
        return httpx.Response(200, json={"ok": True, "channel": "C123", "ts": "1700000000.000100"})

    result = await send_slack_message(
        channel="C123",
        text="hello from TradingOS",
        bot_token="xoxb-test-token",
        transport=httpx.MockTransport(handler),
    )

    assert captured["method"] == "POST"
    assert captured["url"] == "https://slack.com/api/chat.postMessage"
    assert captured["headers"]["authorization"] == "Bearer xoxb-test-token"
    assert b'"channel":"C123"' in captured["body"]
    assert b'"text":"hello from TradingOS"' in captured["body"]
    assert result == {"ok": True, "channel": "C123", "ts": "1700000000.000100"}


@pytest.mark.asyncio
async def test_send_slack_message_raises_on_real_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"ok": False, "error": "internal_error"})

    with pytest.raises(httpx.HTTPStatusError):
        await send_slack_message(
            channel="C123",
            text="hi",
            bot_token="xoxb-test-token",
            transport=httpx.MockTransport(handler),
        )


@pytest.mark.asyncio
async def test_send_slack_message_raises_a_real_runtime_error_on_a_200_but_ok_false_response():
    # A real, confirmed Slack platform quirk: chat.postMessage returns HTTP 200 even on a real
    # failure (e.g. bad token, channel not found) -- raise_for_status() alone would never catch
    # this, so send_slack_message must check the "ok" field itself.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "error": "channel_not_found"})

    with pytest.raises(RuntimeError, match="channel_not_found"):
        await send_slack_message(
            channel="C-does-not-exist",
            text="hi",
            bot_token="xoxb-test-token",
            transport=httpx.MockTransport(handler),
        )
