"""REL-010 E10.2: OmniChannelNotifySkill's own dispatch/config-validation logic, independent of
the real HTTP calls (already covered in isolation by tests/unit/test_notifiers.py). Mocks
src.agents.tools.notifiers's send_* functions directly rather than HTTP transport.
"""

from unittest.mock import AsyncMock, patch

import pytest

from src.agents.tools.skills import OmniChannelNotifySkill, SkillNotImplementedError


@patch("src.agents.tools.skills._telegram_bot_token", return_value="real-token")
@patch("src.agents.tools.skills.send_telegram_message", new_callable=AsyncMock)
def test_telegram_dispatch_calls_the_real_send_function(mock_send, _mock_token):
    mock_send.return_value = {"ok": True}
    result = OmniChannelNotifySkill().execute(channel="telegram", text="hi", chat_id="123")
    assert result == {"ok": True}
    mock_send.assert_awaited_once_with(chat_id="123", text="hi", bot_token="real-token")


def test_telegram_dispatch_raises_when_no_bot_token_configured():
    with (
        patch("src.agents.tools.skills.vault.read_bot_token", return_value=None),
        patch("src.agents.tools.skills.get_settings") as mock_settings,
    ):
        mock_settings.return_value.telegram_bot_token = None
        with pytest.raises(SkillNotImplementedError, match="bot token"):
            OmniChannelNotifySkill().execute(channel="telegram", text="hi", chat_id="123")


@patch("src.agents.tools.skills.send_discord_followup", new_callable=AsyncMock)
def test_discord_dispatch_calls_the_real_send_function(mock_send):
    mock_send.return_value = {"id": "msg-1"}
    result = OmniChannelNotifySkill().execute(
        channel="discord", text="hi", application_id="app-1", interaction_token="tok-1"
    )
    assert result == {"id": "msg-1"}
    mock_send.assert_awaited_once_with(
        application_id="app-1", interaction_token="tok-1", content="hi"
    )


def test_discord_dispatch_raises_when_no_application_id_configured():
    with patch("src.agents.tools.skills.get_settings") as mock_settings:
        mock_settings.return_value.discord_application_id = None
        with pytest.raises(SkillNotImplementedError, match="application_id"):
            OmniChannelNotifySkill().execute(channel="discord", text="hi", interaction_token="t")


@patch("src.agents.tools.skills._slack_bot_token", return_value="real-token")
@patch("src.agents.tools.skills.send_slack_message", new_callable=AsyncMock)
def test_slack_dispatch_calls_the_real_send_function(mock_send, _mock_token):
    mock_send.return_value = {"ok": True, "channel": "C123"}
    result = OmniChannelNotifySkill().execute(channel="slack", text="hi", channel_id="C123")
    assert result == {"ok": True, "channel": "C123"}
    mock_send.assert_awaited_once_with(channel="C123", text="hi", bot_token="real-token")


def test_slack_dispatch_raises_when_no_bot_token_configured():
    with (
        patch("src.agents.tools.skills.vault.read_bot_token", return_value=None),
        patch("src.agents.tools.skills.get_settings") as mock_settings,
    ):
        mock_settings.return_value.slack_bot_token = None
        with pytest.raises(SkillNotImplementedError, match="bot token"):
            OmniChannelNotifySkill().execute(channel="slack", text="hi", channel_id="C123")
