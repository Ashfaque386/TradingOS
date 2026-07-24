from datetime import datetime
from typing import Any

from sqlalchemy import Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, UUIDPKMixin


class ShadowModeAttempt(Base, UUIDPKMixin, TimestampMixin):
    """Shadow Mode dry-run ledger (Phase 4 Epic E4.4, Phase_9_Master_Implementation_Guide.md §4
    go-live gate: "Shadow Mode has run for 5 consecutive days with zero broker API syntax
    errors"). Not part of the original DB-001..027 schema -- new table for this real epic. See
    src/brokers/shadow_mode.py's module docstring for why Upstox and Zerodha attempts mean
    genuinely different things (a real sandbox call vs. local-only payload validation) --
    `used_real_sandbox` records which one produced each row, so the go-live report can be honest
    about it rather than treating every "Validated" row as equally strong evidence.
    """

    __tablename__ = "shadow_mode_attempts"

    broker: Mapped[str] = mapped_column(String(20), nullable=False)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)  # Validated | Error
    error_detail: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    used_real_sandbox: Mapped[bool] = mapped_column(nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(nullable=False)
