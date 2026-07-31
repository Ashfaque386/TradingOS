import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, UUIDPKMixin


class PortfolioAllocationRecommendation(Base, UUIDPKMixin):
    """REL-010 E10.5 (Portfolio Manager Agent, AGT-016). Advisory only -- `recommendations`
    (per-strategy capital-weight suggestions, JSONB) is never auto-applied to any real position
    sizing; the human Portfolio Manager retains override authority via `accept`/`reject`
    (src/api/routers/portfolio.py). `status` starts "Proposed" and is a terminal decision once
    `Accepted`/`Rejected` -- `accept` itself is still just a record of human sign-off (an
    "Accepted" recommendation is not separately re-applied anywhere; see that router's own
    docstring for why: no automated position-sizing execution path exists in this codebase, by
    design, matching Business Rule 3)."""

    __tablename__ = "portfolio_allocation_recommendations"
    __table_args__ = (
        CheckConstraint("status IN ('Proposed', 'Accepted', 'Rejected')", name="ck_status"),
    )

    generated_at: Mapped[datetime] = mapped_column(nullable=False)
    recommendations: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id")
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="Proposed")
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    decided_at: Mapped[datetime | None]
