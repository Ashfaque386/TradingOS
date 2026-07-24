import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, UUIDPKMixin


class Order(Base, UUIDPKMixin):
    """DB-008. Order lifecycle (pre-fill). latency_ms measured against NFR-02 (<50ms)."""

    __tablename__ = "orders"

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    strategy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategies.id"), nullable=False
    )
    broker_order_id: Mapped[str | None] = mapped_column(String(50))
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    order_type: Mapped[str] = mapped_column(String(10), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    limit_price: Mapped[float | None] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    requested_at: Mapped[datetime]
    acknowledged_at: Mapped[datetime | None]
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    rejection_reason: Mapped[str | None] = mapped_column(Text)


class Trade(Base, UUIDPKMixin):
    """DB-009. Executed fills/ledger, incl. Indian tax friction (STT/GST/brokerage) per BR-03."""

    __tablename__ = "trades"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False
    )
    strategy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategies.id"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    brokerage: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    stt: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    gst: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    net_pnl: Mapped[float | None] = mapped_column(Numeric(14, 2))
    executed_at: Mapped[datetime] = mapped_column(nullable=False)


class PortfolioPosition(Base, UUIDPKMixin):
    """DB-010. Live net position and PnL snapshot."""

    __tablename__ = "portfolio_positions"
    __table_args__ = (UniqueConstraint("account_id", "strategy_id", "symbol"),)

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    strategy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategies.id"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    net_quantity: Mapped[int] = mapped_column(Integer, default=0)
    avg_price: Mapped[float | None] = mapped_column(Numeric(12, 2))
    unrealized_pnl: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    realized_pnl: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    as_of: Mapped[datetime]


class RiskLimit(Base, UUIDPKMixin, TimestampMixin):
    """DB-011. Hardcoded risk thresholds (BR-05, FR-08) — always set by a human Risk Manager."""

    __tablename__ = "risk_limits"

    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    max_daily_loss: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    max_position_size_pct: Mapped[float | None] = mapped_column(Numeric(5, 2))
    max_sector_exposure_pct: Mapped[float | None] = mapped_column(Numeric(5, 2))
    max_drawdown_pct: Mapped[float | None] = mapped_column(Numeric(5, 2))
    set_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    effective_from: Mapped[datetime]
