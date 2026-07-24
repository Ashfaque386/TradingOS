import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, UUIDPKMixin


class PaperTrade(Base, UUIDPKMixin, TimestampMixin):
    """Paper Trading Engine ledger (Phase 4 Epic E4.4, Phase_6_Trading_Engine_Design.md §5):
    "Uses live WebSocket tick data but routes orders to a local Postgres ledger instead of the
    broker. Applies aggressive slippage assumptions and partial fill probabilities based on
    real-time order book depth (Level 2 data) to simulate realistic market impact." Not part of
    the original DB-001..027 schema (Phase_11_Database_Design.md never specified a paper-trading
    ledger table) -- new schema for this real epic.

    Every row is a REAL simulated fill against a REAL Level-2 depth snapshot fetched live from
    the configured broker at signal time (src/engine/paper_trading/slippage_model.py walks the
    real depth, no synthetic order book is fabricated) -- only the "did this order actually reach
    an exchange" part is simulated, not the market data driving the simulation.
    """

    __tablename__ = "paper_trades"

    strategy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategies.id")
    )
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)  # BUY | SELL
    requested_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    filled_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    # LTP at signal time
    reference_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    # depth-weighted average
    fill_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    slippage_bps: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False)
    # The real depth levels actually walked to compute fill_price -- kept for audit/replay, not
    # a summary a human is expected to read directly.
    depth_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    executed_at: Mapped[datetime] = mapped_column(nullable=False)
