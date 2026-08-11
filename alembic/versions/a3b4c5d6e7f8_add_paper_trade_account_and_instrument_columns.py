"""add account_id and instrument-type columns to paper_trades (REL-034 Paper Trading Account)

Revision ID: a3b4c5d6e7f8
Revises: e7f8a9b0c1d2
Create Date: 2026-08-11 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable for now -- scripts/seed_paper_account.py backfills any pre-existing rows before
    # a later migration (b4c5d6e7f8a9) tightens this to NOT NULL. Every `paper_trades` row has
    # been keyed only by `strategy_id` until now; this is the real account this ledger has always
    # implicitly belonged to but never recorded.
    op.add_column(
        "paper_trades", sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_paper_trades_account_id", "paper_trades", "accounts", ["account_id"], ["id"]
    )

    # 'EQUITY' backfills every pre-existing row honestly -- no F&O paper trade has ever been
    # placed by the (until now, manual-only) execute_paper_trade() path.
    op.add_column(
        "paper_trades",
        sa.Column("instrument_type", sa.String(length=10), nullable=False, server_default="EQUITY"),
    )
    op.add_column("paper_trades", sa.Column("underlying", sa.String(length=30), nullable=True))
    op.add_column("paper_trades", sa.Column("strike", sa.Numeric(12, 2), nullable=True))
    op.add_column("paper_trades", sa.Column("expiry", sa.Date(), nullable=True))

    # Opportunistic backfill -- a no-op on a fresh DB (no Paper account exists yet), harmless if
    # scripts/seed_paper_account.py happens to have already run before this migration does.
    # Matched on broker = 'PAPER' (that script's own sentinel) as well as account_type = 'Paper'
    # -- confirmed live that this project's pytest suite leaves its own account_type='Paper'
    # fixture rows (broker='Zerodha') behind in this same shared dev database; account_type
    # alone would silently backfill against one of those instead of the real seeded account.
    op.execute(
        "UPDATE paper_trades SET account_id = "
        "(SELECT id FROM accounts WHERE broker = 'PAPER' AND account_type = 'Paper' "
        "ORDER BY created_at LIMIT 1) "
        "WHERE account_id IS NULL "
        "AND EXISTS (SELECT 1 FROM accounts WHERE broker = 'PAPER' AND account_type = 'Paper')"
    )


def downgrade() -> None:
    op.drop_constraint("fk_paper_trades_account_id", "paper_trades", type_="foreignkey")
    op.drop_column("paper_trades", "account_id")
    op.drop_column("paper_trades", "instrument_type")
    op.drop_column("paper_trades", "underlying")
    op.drop_column("paper_trades", "strike")
    op.drop_column("paper_trades", "expiry")
