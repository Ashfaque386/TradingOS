import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin, UUIDPKMixin


class User(Base, UUIDPKMixin, TimestampMixin):
    """DB-001. `role` is one of the 4 canonical strings in src/core/security.py (ALL_ROLES),
    matching Phase_12_Security_Design.md §2.2's RBAC Permission Matrix: SystemAdministrator,
    PortfolioManager, RiskManager, ReadOnlyAuditor. (The matrix's 5th row, AI CEO Agent, is an
    internal service identity with no login flow, so it's not a valid value here.)"""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(150))
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None]

    notification_channels: Mapped[list["NotificationChannel"]] = relationship(back_populates="user")


class NotificationChannel(Base, UUIDPKMixin, TimestampMixin):
    """DB-002. Omni-channel bot bindings (Telegram/WhatsApp/Discord/Slack/Email) per FR-10."""

    __tablename__ = "notification_channels"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    channel_type: Mapped[str] = mapped_column(String(20), nullable=False)
    external_handle: Mapped[str] = mapped_column(String(255), nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    preferences: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    user: Mapped["User"] = relationship(back_populates="notification_channels")
