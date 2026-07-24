import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, UUIDPKMixin


class Skill(Base, UUIDPKMixin, TimestampMixin):
    """DB-015. Plugin/Skill catalog per FR-12 dynamic Skill (Plugin) architecture."""

    __tablename__ = "skills"

    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    pydantic_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class AgentSkillMap(Base, UUIDPKMixin):
    """DB-016. Agent-to-Skill grants."""

    __tablename__ = "agent_skill_map"
    __table_args__ = (UniqueConstraint("agent_name", "skill_id"),)

    agent_name: Mapped[str] = mapped_column(String(50), nullable=False)
    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skills.id"), nullable=False
    )
    granted_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    granted_at: Mapped[datetime]
