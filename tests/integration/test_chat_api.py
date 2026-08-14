"""Omni-Channel Chat API integration test (Phase 4 Epic E4.3): the endpoints wired in
src/api/routers/chat.py, against the real FastAPI app + real Postgres.

Deliberately does NOT wait for a real LLM reply to complete: unlike the ~60-90s real backtest in
test_strategies_api.py, a real chat reply in this environment can take many minutes (OpenCode
Zen currently fails on a missing payment method, so most calls fall through to a local Ollama
reasoning model) -- waiting for that every test run would make the suite impractically slow.
This test instead verifies the real synchronous path: the user message and a real "Pending"
assistant placeholder are both actually persisted to Postgres, and the async dispatch itself
doesn't error, without asserting on the eventual reply content.
"""

import uuid

from fastapi.testclient import TestClient

from src.agents.prompt_registry import get_active_prompt
from src.api.main import app
from src.api.routers.chat import PROMPT_SLUG, _build_messages
from src.core.db import get_session
from src.models.chat import ChatMessage

client = TestClient(app)


def _cleanup(*message_ids: uuid.UUID | None) -> None:
    ids = [m for m in message_ids if m is not None]
    if not ids:
        return
    with get_session() as session:
        for message_id in ids:
            session.query(ChatMessage).filter(ChatMessage.id == message_id).delete()
        session.commit()


def test_send_message_persists_and_returns_a_pending_assistant_row():
    unique_marker = f"integration-test-{uuid.uuid4()}"
    response = client.post("/api/v1/chat/messages", json={"content": unique_marker})
    assert response.status_code == 202
    body = response.json()
    assert body["role"] == "assistant"
    assert body["status"] == "Pending"
    assistant_id = uuid.UUID(body["id"])

    user_id = None
    try:
        list_response = client.get("/api/v1/chat/messages")
        assert list_response.status_code == 200
        messages = list_response.json()

        user_messages = [
            m for m in messages if m["role"] == "user" and m["content"] == unique_marker
        ]
        assert len(user_messages) == 1
        user_id = uuid.UUID(user_messages[0]["id"])

        assistant_messages = [m for m in messages if m["id"] == str(assistant_id)]
        assert len(assistant_messages) == 1
        assert assistant_messages[0]["status"] == "Pending"
    finally:
        _cleanup(user_id, assistant_id)


def test_send_empty_message_is_rejected():
    response = client.post("/api/v1/chat/messages", json={"content": "   "})
    assert response.status_code == 422


# PMPT-026 regression coverage: _build_messages() is the real function that wires the chat
# prompt into the actual LLM call generate_and_store_reply() makes -- exercised directly here
# (real prompt registry, real DB-backed kill-switch/strategy lookups) rather than waiting on a
# live LLM reply, for the same slow-completion reason the tests above don't either.


def test_build_messages_uses_the_real_pmpt_026_prompt_and_real_system_context():
    prompt = get_active_prompt(PROMPT_SLUG)

    messages = _build_messages(history=[], new_user_content="What's my current risk exposure?")

    assert messages[0] == {"role": "system", "content": prompt}
    assert messages[1]["role"] == "system"
    # _real_system_context() gathers each fact defensively (try/except per fact) so a DB hiccup
    # drops just that fact rather than the whole reply -- either the real fact or its own
    # honest "unavailable" fallback text must be present, never a silent gap.
    assert messages[1]["content"].startswith("Current real system state:")
    assert "Kill switch" in messages[1]["content"]
    assert (
        "Strategies by status" in messages[1]["content"]
        or "No strategies exist yet." in (messages[1]["content"])
        or "Strategy summary unavailable" in messages[1]["content"]
    )
    assert messages[-1] == {"role": "user", "content": "What's my current risk exposure?"}


def test_build_messages_drops_a_still_pending_assistant_reply_but_keeps_all_user_turns():
    """The real history filter is `if status == "Completed" or role == "user"` -- a bug here
    would replay an empty/Pending or Failed assistant placeholder back into the model's own
    context, corrupting the conversation it sees."""
    history = [
        ("user", "hi", "Completed"),
        ("assistant", "hello", "Completed"),
        ("user", "are you done yet?", "Completed"),
        ("assistant", "", "Pending"),
    ]

    messages = _build_messages(history=history, new_user_content="new question")

    replayed = [(m["role"], m["content"]) for m in messages[2:]]  # skip the 2 system messages
    assert replayed == [
        ("user", "hi"),
        ("assistant", "hello"),
        ("user", "are you done yet?"),
        ("user", "new question"),
    ]
