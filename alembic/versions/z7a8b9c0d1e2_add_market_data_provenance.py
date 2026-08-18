"""add market_data_provenance table (REL-073, Phase 4 of the Upstox V3 + yfinance dual
market-data system)

Revision ID: z7a8b9c0d1e2
Revises: y6z7a8b9c0d1
Create Date: 2026-08-18 00:00:00.000000

A real, small, one-row-per-symbol record of the most recent successful managed/scheduled OHLCV
fetch -- closes the gap `run_real_backtest()` can't answer on its own: the Parquet data lake
carries no per-row provider/fetch-time column, so "which provider supplied this backtest's data"
has no real source of truth without this table. Deliberately not a full per-row audit trail
(this phase's own approved scope: "prefer... not must... not a full data-snapshot/hash system").
Starts empty -- the first real managed/scheduled ingestion run populates it.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "z7a8b9c0d1e2"
down_revision: Union[str, None] = "y6z7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "market_data_provenance",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("symbol", sa.String(length=30), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", name="uq_market_data_provenance_symbol"),
    )


def downgrade() -> None:
    op.drop_table("market_data_provenance")
