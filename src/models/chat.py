import uuid
from typing import Any

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, UUIDPKMixin


class ChatMessage(Base, UUIDPKMixin, TimestampMixin):
    """Omni-Channel Chat (Phase 4 Epic E4.3, Phase_7_Frontend_Architecture.md §2.5). Not part of
    the original DB-001..DB-018 schema (Phase_11_Database_Design.md) -- the ERD never specified
    a conversational chat surface, only the batch-oriented AI Agent pipeline (AgentRun/AgentLog)
    and the omni-channel *bot webhook* ingestion path (WebhookEvent, DB-018, for inbound
    Telegram/Discord/etc. messages). This table is new schema for the in-dashboard chat UI
    specifically, a distinct concern from WebhookEvent.

    `status` mirrors the async-job pattern used elsewhere (BacktestJob in
    src/api/routers/strategies.py, AgentRun): a user message is always "Complete" the moment
    it's saved; an assistant reply starts "Pending" and is updated in place once the real LLM
    call in a background thread finishes -- these calls can take minutes in this environment
    (see src/api/routers/chat.py's module docstring), so nothing here pretends to be
    synchronous.

    REL-010 E10.1: `channel`/`external_metadata`/`webhook_event_id` let this same, already-real
    reply pipeline be reused for Telegram/Discord messages, not just the dashboard -- `channel`
    defaults to "Web" so every pre-REL-010 row (and the dashboard's own behavior) is unchanged.
    `external_metadata` holds the per-platform routing info a reply needs (e.g. Telegram's
    `chat_id`, Discord's `interaction_token`/`application_id`) -- never a TradingOS user identity
    (see src/api/routers/webhooks.py's own docstring on why that mapping is still out of scope).
    """

    __tablename__ = "chat_messages"

    role: Mapped[str] = mapped_column(String(10), nullable=False)  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="Complete")
    error: Mapped[str | None] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="Web")
    external_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    webhook_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("webhook_events.id", ondelete="SET NULL")
    )
