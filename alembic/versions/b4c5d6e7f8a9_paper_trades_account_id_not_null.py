"""tighten paper_trades.account_id to NOT NULL (REL-034 Paper Trading Account)

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-08-11 00:00:00.000001

Deliberately deployed strictly after `scripts/seed_paper_account.py` has run (it seeds the one
Paper `Account` row and backfills any pre-existing `paper_trades.account_id IS NULL` rows to it).
Postgres itself enforces the correct operational order here: `ALTER COLUMN ... SET NOT NULL`
fails loudly with a real Postgres error if any row is still unbackfilled, rather than this
migration silently succeeding and leaving a subtly-broken invariant for later code to trip over.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, None] = "a3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("paper_trades", "account_id", nullable=False)


def downgrade() -> None:
    op.alter_column("paper_trades", "account_id", nullable=True)
