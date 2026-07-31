"""Omni-Channel Chat (Phase 4 Epic E4.3), backing Phase_7_Frontend_Architecture.md §2.5's
"Premium Chat Interface... natural language conversations with the CEO Agent."

This is deliberately NOT a call into `src/agents/nodes/ceo.py`'s `ceo_agent_node`: that node's
whole contract is a fixed JSON schema (`ResearchDirective`) for the batch LangGraph pipeline --
forcing free-form chat through it would either break the schema or produce garbage. Instead this
uses a separate, real prompt (`ceo_agent_chat`, PMPT-026, src/agents/prompts/ceo_agent_chat/v1.md)
through the same real `src/agents/llm_router.py` gateway, kept on its own prompt slug specifically
so hot-swapping a version in the Agent Console's Prompt Management UI can never accidentally
break the batch pipeline (they don't share a slug).

Every reply is a real LLM call, dispatched via a detached daemon thread (see
src/api/routers/agents.py's `trigger_research` for why: Starlette's BackgroundTasks would block
graceful shutdown on a slow call, and calls here can take minutes in this environment -- OpenCode
Zen currently fails on a missing payment method, so most calls fall through to a local Ollama
reasoning model, deepseek-r1, which is slow on this host). The assistant's message row starts
"Pending" and the frontend polls for it to flip to "Completed"/"Failed".

Real system context (kill-switch state, a strategy status breakdown) is injected before the
user's message so the model answers from actual state rather than inventing numbers -- gathered
defensively (try/except per fact) so a DB hiccup drops that one fact rather than failing the
whole reply, matching the fallback-on-failure pattern used throughout src/agents/nodes/.

REL-010 E10.1: `channel`/`external_metadata`/`webhook_event_id` were added to `ChatMessage` so
this same real, tested reply pipeline could be reused verbatim for omni-channel (Telegram/
Discord) messages -- src/api/routers/webhooks.py calls `generate_and_store_reply` directly with
an `on_complete` callback rather than reimplementing the LLM-call/pending-row/thread machinery.
`channel` defaults to "Web" everywhere so the existing dashboard frontend's behavior (and every
pre-REL-010 test/call site) is unchanged.
"""

import threading
import uuid
from collections.abc import Callable
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select

from src.agents.llm_router import NoProviderAvailableError, complete
from src.agents.prompt_registry import get_active_prompt
from src.core.db import get_session
from src.engine.risk import kill_switch_service
from src.models.chat import ChatMessage
from src.models.strategy import Strategy

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

PROMPT_SLUG = "ceo_agent_chat"


class ChatMessageResponse(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    status: str
    error: str | None
    created_at: datetime


class SendMessageRequest(BaseModel):
    content: str


def _to_response(message: ChatMessage) -> ChatMessageResponse:
    return ChatMessageResponse(
        id=message.id,
        role=message.role,
        content=message.content,
        status=message.status,
        error=message.error,
        created_at=message.created_at,
    )


@router.get("/messages", response_model=list[ChatMessageResponse])
def list_messages(channel: str = "Web") -> list[ChatMessageResponse]:
    """`channel` defaults to "Web" -- the pre-REL-010 dashboard behavior is unchanged unless a
    caller (webhooks.py's own history reads, or a future admin view) explicitly asks for
    another channel's thread."""
    with get_session() as session:
        messages = session.scalars(
            select(ChatMessage)
            .where(ChatMessage.channel == channel)
            .order_by(ChatMessage.created_at)
        )
        return [_to_response(m) for m in messages]


def _real_system_context() -> str:
    facts: list[str] = []

    try:
        status = kill_switch_service.get_status()
        facts.append(f"Kill switch: {status['state']} (tripped_at={status['tripped_at']})")
    except Exception as exc:  # noqa: BLE001 - one missing fact shouldn't sink the whole reply
        facts.append(f"Kill switch status unavailable ({exc})")

    try:
        with get_session() as session:
            rows = session.execute(
                select(Strategy.status, func.count()).group_by(Strategy.status)
            ).all()
        if rows:
            breakdown = ", ".join(f"{count} {status}" for status, count in rows)
            facts.append(f"Strategies by status: {breakdown}")
        else:
            facts.append("No strategies exist yet.")
    except Exception as exc:  # noqa: BLE001
        facts.append(f"Strategy summary unavailable ({exc})")

    return "Current real system state:\n" + "\n".join(f"- {f}" for f in facts)


def _build_messages(
    history: list[tuple[str, str, str]], new_user_content: str
) -> list[dict[str, str]]:
    """`history` is (role, content, status) tuples, not ORM objects -- kept self-contained to
    this thread's DB access rather than a detached ORM instance handed across threads, same
    pattern as src/api/routers/strategies.py's `_run_backtest_job`."""
    system_prompt = get_active_prompt(PROMPT_SLUG)
    messages = [{"role": "system", "content": system_prompt}]
    messages.append({"role": "system", "content": _real_system_context()})
    for role, content, status in history:
        if status == "Completed" or role == "user":
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": new_user_content})
    return messages


def generate_and_store_reply(
    *,
    assistant_message_id: uuid.UUID,
    history: list[tuple[str, str, str]],
    user_content: str,
    on_complete: Callable[[str, str], None] | None = None,
) -> None:
    """Real LLM call + resolves the pending assistant row. REL-010 E10.1: extracted from the
    dashboard's own `send_message` so src/api/routers/webhooks.py can reuse this exact, already-
    tested reply pipeline for Telegram/Discord messages rather than reimplementing it.
    `on_complete(reply_text, status)` fires (in this same background thread) once the row update
    has committed -- webhooks.py uses it to dispatch the real outbound notify skill and update
    the originating WebhookEvent row; this module has no knowledge of webhooks.py itself."""
    try:
        response = complete("chat", messages=_build_messages(history, user_content))
        reply = response.choices[0].message.content
        with get_session() as session:
            assistant_message = session.get(ChatMessage, assistant_message_id)
            if assistant_message is not None:
                assistant_message.content = reply
                assistant_message.status = "Completed"
                session.commit()
        if on_complete is not None:
            on_complete(reply, "Completed")
    except NoProviderAvailableError as exc:
        with get_session() as session:
            assistant_message = session.get(ChatMessage, assistant_message_id)
            if assistant_message is not None:
                assistant_message.status = "Failed"
                assistant_message.error = str(exc)
                assistant_message.content = ""
                session.commit()
        if on_complete is not None:
            on_complete("", "Failed")
    except Exception as exc:  # noqa: BLE001 - must always resolve the pending row, even on a bug
        with get_session() as session:
            assistant_message = session.get(ChatMessage, assistant_message_id)
            if assistant_message is not None:
                assistant_message.status = "Failed"
                assistant_message.error = str(exc)
                assistant_message.content = ""
                session.commit()
        if on_complete is not None:
            on_complete("", "Failed")


@router.post("/messages", response_model=ChatMessageResponse, status_code=202)
def send_message(body: SendMessageRequest) -> ChatMessageResponse:
    if not body.content.strip():
        raise HTTPException(status_code=422, detail="Message content cannot be empty")

    with get_session() as session:
        history = [
            (m.role, m.content, m.status)
            for m in session.scalars(
                select(ChatMessage)
                .where(ChatMessage.channel == "Web")
                .order_by(ChatMessage.created_at)
            )
        ]

        user_message = ChatMessage(
            role="user", content=body.content, status="Completed", channel="Web"
        )
        session.add(user_message)
        session.flush()

        assistant_message = ChatMessage(
            role="assistant", content="", status="Pending", channel="Web"
        )
        session.add(assistant_message)
        session.commit()
        assistant_id = assistant_message.id

    threading.Thread(
        target=generate_and_store_reply,
        kwargs={
            "assistant_message_id": assistant_id,
            "history": history,
            "user_content": body.content,
        },
        daemon=True,
    ).start()

    with get_session() as session:
        assistant_row = session.get(ChatMessage, assistant_id)
        if assistant_row is None:
            raise HTTPException(status_code=500, detail="Assistant message row vanished")
        return _to_response(assistant_row)
