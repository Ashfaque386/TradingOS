from datetime import datetime
from typing import Any

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, UUIDPKMixin


class WebhookEvent(Base, UUIDPKMixin):
    """DB-018. Raw + normalized inbound omni-channel messages (Telegram/Discord/WhatsApp/Slack).
    30-day retention only — operational debugging, not a system of record (Phase_11 §5.2)."""

    __tablename__ = "webhook_events"

    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    user_message_raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    normalized_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    routed_to_agent: Mapped[str | None] = mapped_column(String(50))
    response_sent: Mapped[str | None]
    received_at: Mapped[datetime]
