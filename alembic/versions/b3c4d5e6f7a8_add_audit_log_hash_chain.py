"""add hash-chain columns + append-only trigger to audit_log (REL-006 E6.2, SEC-037/038/041)

Revision ID: b3c4d5e6f7a8
Revises: f6a7b8c9d0e1
Create Date: 2026-07-26 09:00:00.000000

Honest gap (documented here, in src/models/audit.py, and in src/core/audit.py): this
environment has exactly one Postgres role ("tradingos"), which owns this table. The trigger
below is a real, unconditional BEFORE UPDATE OR DELETE guard -- it fires regardless of caller
role, which is what actually stops every application-level and non-owner-SQL path (SEC-037,
SEC-041's "no privileged bypass"). But a session connected as the table OWNER can still issue
`ALTER TABLE audit_log DISABLE TRIGGER audit_log_no_mutation` or
`SET session_replication_role = replica` and bypass it. A truly bypass-proof SEC-041 needs a
second, non-owner "audit_writer" Postgres role reached over a separate connection string --
that is an infra change out of scope here (single-role Postgres is this environment's
standing setup) and is tracked as a REL-009/infra-hardening follow-up, not silently claimed as
solved. The REVOKE statements below are real defense-in-depth for the non-owner case, not a
complete answer to the owner-bypass case.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

GENESIS_PREV_HASH = "0" * 64


def upgrade() -> None:
    op.add_column("audit_log", sa.Column("entry_hash", sa.String(length=64), nullable=True))
    op.add_column("audit_log", sa.Column("prev_entry_hash", sa.String(length=64), nullable=True))

    # Backfill guard: confirmed zero writers exist anywhere in the codebase as of REL-006, so no
    # pre-existing rows are expected -- this UPDATE is a safety net, not a real migration of real
    # data, and is documented as such rather than silently assumed unnecessary.
    op.execute(
        f"UPDATE audit_log SET entry_hash = encode(sha256(id::text::bytea), 'hex'), "
        f"prev_entry_hash = '{GENESIS_PREV_HASH}' WHERE entry_hash IS NULL"
    )
    op.alter_column("audit_log", "entry_hash", nullable=False)
    op.alter_column("audit_log", "prev_entry_hash", nullable=False)

    # SEC-037/SEC-041: unconditional trigger, no role exemption possible by construction.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_log_prevent_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only: % is not permitted (SEC-037/SEC-041)', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_log_no_mutation
        BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION audit_log_prevent_mutation();
        """
    )

    # Defense-in-depth for the non-owner case (see module docstring for the owner-bypass gap).
    op.execute("REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC")
    op.execute("REVOKE UPDATE, DELETE ON audit_log FROM tradingos")
    op.execute("GRANT INSERT, SELECT ON audit_log TO tradingos")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_mutation ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS audit_log_prevent_mutation()")
    op.execute("GRANT UPDATE, DELETE ON audit_log TO tradingos")
    op.drop_column("audit_log", "prev_entry_hash")
    op.drop_column("audit_log", "entry_hash")
