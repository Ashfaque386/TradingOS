import uuid
from datetime import datetime

from sqlalchemy import CHAR, Boolean, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, UUIDPKMixin


class Account(Base, UUIDPKMixin, TimestampMixin):
    """DB-003. Broker trading account (Paper or Live per SRS Business Rule 3)."""

    __tablename__ = "accounts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    broker: Mapped[str] = mapped_column(String(20), nullable=False)
    account_type: Mapped[str] = mapped_column(String(20), nullable=False)
    capital_allocated: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), default="INR")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class BrokerCredential(Base, UUIDPKMixin, TimestampMixin):
    """DB-004. Vault secret pointer only — actual key material never lives in Postgres (NFR-04)."""

    __tablename__ = "broker_credentials"

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    key_type: Mapped[str] = mapped_column(String(20), nullable=False)
    vault_secret_path: Mapped[str] = mapped_column(String(255), nullable=False)
    rotated_at: Mapped[datetime | None]
    expires_at: Mapped[datetime | None]
