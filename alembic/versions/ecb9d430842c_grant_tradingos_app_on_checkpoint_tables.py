"""grant tradingos_app on the real LangGraph checkpointer tables (fixes REL-060's own gap)

Revision ID: ecb9d430842c
Revises: 2fc35def329f
Create Date: 2026-09-05 00:00:00.000000

Found via a real, reproduced CI failure: `test_pause_after_one_node_then_resume_runs_only_the_
remaining_nodes_once` failed with `permission denied for table checkpoints` against a genuinely
fresh Postgres, even though a1a5d7f7bb58's own comment claimed `u2v3w4x5y6z7`'s `ALTER DEFAULT
PRIVILEGES` rule already covered these tables with "zero followup GRANTs" needed.

Root cause, confirmed by direct proof against an isolated throwaway Postgres (a debug query run
from inside `PostgresSaver`'s own connection, immediately before `.setup()`, showed
`pg_default_acl` completely empty even though `u2v3w4x5y6z7` had already run many migrations
earlier in the same invocation): `alembic upgrade head` runs its entire migration sequence inside
ONE single transaction (`alembic/env.py`'s `context.begin_transaction()` wraps the whole
`run_migrations()` loop, not one transaction per script). `PostgresSaver.setup()` (called from
a1a5d7f7bb58) opens a genuinely SEPARATE psycopg connection -- not Alembic's own -- which can
only see already-COMMITTED state from other transactions under normal READ COMMITTED isolation.
Since `u2v3w4x5y6z7`'s `ALTER DEFAULT PRIVILEGES` is still uncommitted (part of the same giant
in-flight transaction) at the moment `PostgresSaver` creates its tables, no default privilege
ever applies to them.

a1a5d7f7bb58's own "verified end-to-end" claim was real, but tested against an already-migrated
dev database where that ALTER DEFAULT PRIVILEGES had already been committed by a separate, much
earlier `alembic upgrade head` run -- masking this gap on any database that has never run every
migration in one shot, which is exactly what a fresh CI Postgres (and any fresh deployment) does.

Not fixed by editing a1a5d7f7bb58 directly: that migration is already applied on this project's
own dev database (and would be on any other already-migrated environment), and migrations in this
project are treated as an immutable historical record -- a follow-up migration is the correct,
established pattern here (e.g. 2fc35def329f itself was a follow-up fixing a different, earlier
gap the same way). The GRANT statements below are plain idempotent SQL (re-granting an
already-held privilege is a no-op in Postgres), safe to apply to every environment regardless of
whether it already has these tables' grants correctly or not.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "ecb9d430842c"
down_revision: str | None = "2fc35def329f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON "
        "checkpoints, checkpoint_blobs, checkpoint_writes, checkpoint_migrations "
        "TO tradingos_app"
    )


def downgrade() -> None:
    # Deliberately a no-op: revoking this would re-break the real pause/resume mechanism for the
    # low-privilege runtime role on any database this migration has already fixed, for no
    # corresponding benefit -- the same asymmetric-downgrade precedent a1a5d7f7bb58 itself already
    # set for these same tables (see its own downgrade()'s comment).
    pass
