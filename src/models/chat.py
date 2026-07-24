from sqlalchemy import String, Text
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
    synchronous."""

    __tablename__ = "chat_messages"

    role: Mapped[str] = mapped_column(String(10), nullable=False)  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="Complete")
    error: Mapped[str | None] = mapped_column(Text)
