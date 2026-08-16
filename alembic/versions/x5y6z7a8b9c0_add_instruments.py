"""add instruments table (REL-071, Phase 2 of the Upstox V3 + yfinance dual market-data system)

Revision ID: x5y6z7a8b9c0
Revises: w4x5y6z7a8b9
Create Date: 2026-08-16 00:00:00.000000

A real, locally-synced copy of Upstox's own real instrument master
(src/data/ingest/instrument_sync.py), closing the honest gap Phase 1 (REL-070) stated:
UpstoxV3Provider needs a real instrument_key (e.g. "NSE_EQ|INE002A01018"), and nothing in this
codebase could resolve a bare symbol like "RELIANCE" into one until this table exists. Starts
empty -- the first real sync run populates it from Upstox's own live instrument files.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "x5y6z7a8b9c0"
down_revision: Union[str, None] = "w4x5y6z7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "instruments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("instrument_key", sa.String(length=100), nullable=False),
        sa.Column("exchange", sa.String(length=10), nullable=False),
        sa.Column("segment", sa.String(length=20), nullable=False),
        sa.Column("symbol", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("instrument_type", sa.String(length=20), nullable=False),
        sa.Column("isin", sa.String(length=20), nullable=True),
        sa.Column("expiry", sa.Date(), nullable=True),
        sa.Column("strike", sa.Numeric(12, 2), nullable=True),
        sa.Column("lot_size", sa.Integer(), nullable=True),
        sa.Column("tick_size", sa.Numeric(10, 4), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "instrument_key", name="uq_instruments_provider_key"),
    )
    op.create_index("ix_instruments_symbol", "instruments", ["symbol"])
    op.create_index("ix_instruments_exchange_type", "instruments", ["exchange", "instrument_type"])


def downgrade() -> None:
    op.drop_index("ix_instruments_exchange_type", table_name="instruments")
    op.drop_index("ix_instruments_symbol", table_name="instruments")
    op.drop_table("instruments")
