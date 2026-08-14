import uuid
from datetime import date, datetime

from sqlalchemy import CHAR, Boolean, ForeignKey, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, UUIDPKMixin
from src.models.tenant import DEFAULT_TENANT_ID


class Account(Base, UUIDPKMixin, TimestampMixin):
    """DB-003. Broker trading account (Paper or Live per SRS Business Rule 3)."""

    __tablename__ = "accounts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    # REL-064 (API-015): every row backfilled onto one seeded "Primary Tenant" at migration time
    # (alembic/versions/w4x5y6z7a8b9) -- existing single-tenant behavior is unchanged.
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id"),
        nullable=False,
        server_default=text(f"'{DEFAULT_TENANT_ID}'"),
    )
    broker: Mapped[str] = mapped_column(String(20), nullable=False)
    account_type: Mapped[str] = mapped_column(String(20), nullable=False)
    capital_allocated: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), default="INR")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class AccountEquitySnapshot(Base, UUIDPKMixin, TimestampMixin):
    """REL-034: one row per account per real trading day -- the one deliberate exception to
    src/engine/paper_trading/position_accounting.py's usual "replay from the immutable ledger,
    never cache" philosophy. See alembic/versions/c5d6e7f8a9b0's own docstring for why: an
    equity curve queried repeatedly over months would otherwise force a full ledger replay plus
    a historical close-price lookup per day in range on every single poll, unlike every other
    figure in this feature (bounded by *currently open* positions only). Written once daily by
    src/engine/paper_trading/equity_snapshot.py; "today" (not yet snapshotted) is always
    computed live instead, never estimated from a stale prior row."""

    __tablename__ = "account_equity_snapshots"
    __table_args__ = (
        UniqueConstraint("account_id", "snapshot_date", name="uq_account_equity_snapshot_date"),
    )

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    snapshot_date: Mapped[date] = mapped_column(nullable=False)
    cash: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    realized_pnl_cumulative: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    unrealized_pnl: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    margin_blocked: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    equity: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)


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
