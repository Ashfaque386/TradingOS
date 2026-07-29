"""add mfa_backup_codes table (REL-007 E7.1, SEC-014)

Revision ID: g7h8i9j0k1l2
Revises: b3c4d5e6f7a8
Create Date: 2026-07-26 12:00:00.000000

No change to `users` -- `mfa_enabled` already exists on that table (added in the initial
schema, previously dead/unread). TOTP secrets themselves live in Vault KV
(secret/mfa-secrets/<user_id>, src/core/vault.py), not Postgres, matching this codebase's
existing "Vault secret pointer only -- actual key material never lives in Postgres" principle
(src/api/routers/settings.py). Backup codes are the one piece of MFA material that DOES belong
in Postgres: they're bcrypt-hashed (irreversible, no secrecy requirement beyond that), single-use,
and need to survive a Vault wipe as a real recovery path when the TOTP secret can't.

`ondelete="CASCADE"` on user_id: a backup code is meaningless without its user, and (found via a
real ForeignKeyViolation in the test suite, not anticipated in advance) test cleanup helpers
hard-delete User rows directly -- without CASCADE, any test that enrolls MFA leaves an orphaned
FK reference that fails on cleanup.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "g7h8i9j0k1l2"
down_revision: Union[str, None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mfa_backup_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code_hash", sa.String(length=255), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_mfa_backup_codes_user_id", "mfa_backup_codes", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_mfa_backup_codes_user_id", table_name="mfa_backup_codes")
    op.drop_table("mfa_backup_codes")
