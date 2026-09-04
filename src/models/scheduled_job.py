import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, UUIDPKMixin


class ScheduledJobConfig(Base, UUIDPKMixin):
    """DB-040 (REL-081). Runtime-editable schedule override for a real in-process
    `apscheduler` job (`src/agents/scheduler.py::JOB_REGISTRY`). No row for a given `job_id`
    means "use the hardcoded `default_cron` + enabled" -- the same fail-open, no-row-means-
    default convention `AgentControlState` already established (only an explicit edit ever
    creates a row here, matching that table's own "starts empty" precedent). This table is the
    source of truth for *schedule*, never for the job's own execution mechanism -- see
    `scheduler.py`'s own module docstring for why a persistent APScheduler job store was
    deliberately not adopted."""

    __tablename__ = "scheduled_job_config"

    job_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    cron_expression: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    updated_at: Mapped[datetime] = mapped_column(nullable=False)


class ScheduledJobRun(Base, UUIDPKMixin):
    """DB-041 (REL-081). Real execution-history ledger -- one row per real firing (cron or
    manual "Run Now") of any job in `scheduler.py::JOB_REGISTRY`. Not unique on `job_id`: many
    rows accumulate per job over time, the real history this feature exists to show. Written by
    `scheduler.py`'s own `_tracked`/`_tracked_async` wrappers, reused identically for both a
    real cron fire and a Run Now dispatch -- `trigger_source` is the only thing that
    distinguishes them."""

    __tablename__ = "scheduled_job_run"
    __table_args__ = (Index("ix_scheduled_job_run_job_id_started_at", "job_id", "started_at"),)

    job_id: Mapped[str] = mapped_column(String(100), nullable=False)
    trigger_source: Mapped[str] = mapped_column(String(10), nullable=False)  # "cron" | "manual"
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="Running")
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column()
    result_summary: Mapped[str | None] = mapped_column(Text)
    triggered_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
