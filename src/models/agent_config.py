"""Per-agent configuration overlay (spec T008, data-model.md §9-§10, FR-100..110, clarify Q4/Q5).

``AgentConfig`` -- one row per agent: provider/model mode (``AUTO`` = today's routing, unchanged;
deterministic agents carry ``None``) and the active prompt-version references. All writes are
``SystemAdministrator``-only and audited (service layer).

``PromptVersion`` -- an immutable version of an agent's system or task prompt. Seeded from the
current file-based prompts on first migration so nothing changes until someone activates a new
version. At most one ``is_active`` row per ``(agent_slug, kind)`` (partial unique index in the
migration).
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, UUIDPKMixin


class AgentConfig(Base, UUIDPKMixin):
    __tablename__ = "agent_configs"

    agent_slug: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    is_llm_backed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # "AUTO" | "CUSTOM"; NULL for deterministic agents (no picker -- FR-104 / clarify Q5).
    provider_model_mode: Mapped[str | None] = mapped_column(String(10))
    custom_provider: Mapped[str | None] = mapped_column(String(40))
    custom_model: Mapped[str | None] = mapped_column(String(120))
    active_system_prompt_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prompt_versions.id", use_alter=True)
    )
    active_task_prompt_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prompt_versions.id", use_alter=True)
    )
    updated_by: Mapped[str | None] = mapped_column(String(255))
    updated_at: Mapped[datetime]


class PromptVersion(Base, UUIDPKMixin):
    __tablename__ = "prompt_versions"
    __table_args__ = (
        UniqueConstraint("agent_slug", "kind", "version", name="uq_prompt_version_triple"),
    )

    agent_slug: Mapped[str] = mapped_column(String(50), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # "system" | "task"
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str] = mapped_column(String(255), nullable=False)
    change_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime]
