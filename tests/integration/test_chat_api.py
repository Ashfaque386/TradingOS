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

from src.api.main import app
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
