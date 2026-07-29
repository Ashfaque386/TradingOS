import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, UUIDPKMixin


class RiskLimitChangeRequest(Base, UUIDPKMixin, TimestampMixin):
    """REL-007 E7.4 (SEC-013/041): dual-control maker-checker for RiskLimit mutations -- the one
    explicit dual-control line in Phase_12_Security_Design.md's RBAC matrix ("Change hard risk
    parameters ... Yes (dual-control, SEC-013)"). Mirrors RiskLimit's own content columns; the
    proposed values live here until a second, distinct privileged user confirms them, at which
    point a real RiskLimit row is created (resulting_risk_limit_id points to it).

    Kill-switch trip/reset are deliberately NOT covered by this table -- see
    src/api/routers/risk_limits.py's module docstring for why."""

    __tablename__ = "risk_limit_change_requests"

    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    max_daily_loss: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    max_position_size_pct: Mapped[float | None] = mapped_column(Numeric(5, 2))
    max_sector_exposure_pct: Mapped[float | None] = mapped_column(Numeric(5, 2))
    max_drawdown_pct: Mapped[float | None] = mapped_column(Numeric(5, 2))
    effective_from: Mapped[datetime]

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    staged_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    confirmed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    decided_at: Mapped[datetime | None]
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    resulting_risk_limit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("risk_limits.id")
    )
