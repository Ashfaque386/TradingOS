"""add account_equity_snapshots table (REL-034 Paper Trading Account)

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-08-11 00:00:00.000002

A deliberate, one-time exception to this ledger's usual "replay from the immutable trade log,
never cache" philosophy (src/engine/paper_trading/position_accounting.py). Every other figure in
this feature is cheap to replay on every read because it's bounded by *currently open* positions
only -- an equity curve queried over months would instead force a full ledger replay plus a
historical close-price lookup per day in range, on every single poll, a cost that grows with
account age unlike anything else here. One row per account per real trading day.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c5d6e7f8a9b0"
down_revision: Union[str, None] = "b4c5d6e7f8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "account_equity_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("cash", sa.Numeric(18, 2), nullable=False),
        sa.Column("realized_pnl_cumulative", sa.Numeric(18, 2), nullable=False),
        sa.Column("unrealized_pnl", sa.Numeric(18, 2), nullable=False),
        sa.Column("margin_blocked", sa.Numeric(18, 2), nullable=False),
        sa.Column("equity", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("account_id", "snapshot_date", name="uq_account_equity_snapshot_date"),
    )


def downgrade() -> None:
    op.drop_table("account_equity_snapshots")
