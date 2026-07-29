import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, String, Text
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class AuditLog(Base):
    """DB-014. Append-only / immutable per BR-05 (REL-006 E6.2). Real enforcement as of the
    b3c4d5e6f7a8 migration: a Postgres BEFORE UPDATE OR DELETE trigger unconditionally rejects
    mutation (SEC-037/SEC-041), plus REVOKE UPDATE/DELETE from the app role as defense-in-depth
    for the non-owner case. entry_hash/prev_entry_hash form a SHA-256 hash chain (SEC-038) --
    see src/core/audit.py for the write path and verification job. Known gap: this environment's
    single Postgres role also owns the table, so a session connected as the owner can still
    disable the trigger -- see the migration's docstring for the full honest-gap note; this is
    not silently claimed as bypass-proof against a DB owner/superuser."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    before_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    prompt_snapshot: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime]
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prev_entry_hash: Mapped[str] = mapped_column(String(64), nullable=False)
