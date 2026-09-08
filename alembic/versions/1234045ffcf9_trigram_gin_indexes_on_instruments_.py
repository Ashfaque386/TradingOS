"""trigram GIN indexes on instruments.symbol/name for fast option search (REL-088)

Revision ID: 1234045ffcf9
Revises: ecb9d430842c
Create Date: 2026-09-08 18:22:38.480680

REL-088 brought ~66k real NSE option contracts (CE/PE) into the `instruments` table, taking it
from ~3.7k rows to ~70k. `src/data/instruments.py::search`'s `symbol ILIKE '%q%' OR name ILIKE
'%q%'` has a leading wildcard, so the existing plain btree `ix_instruments_symbol` can't help it
-- a real `EXPLAIN ANALYZE` on the live table after the option sync showed a sequential scan at
~260-390 ms per query, too slow for a search-as-you-type combobox.

`pg_trgm` + a GIN index over `symbol`/`name` makes a leading-wildcard `ILIKE` index-assisted
(single-digit ms). `CREATE EXTENSION` needs a privileged role -- migrations run as the
schema-owning `tradingos` role (MIGRATION_DATABASE_URL), which has it; the low-privilege
`tradingos_app` runtime role only ever reads through the index. `IF NOT EXISTS` on both the
extension and the indexes keeps this idempotent and safe on an environment that somehow already
has them.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "1234045ffcf9"
down_revision: str | None = "ecb9d430842c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_instruments_symbol_trgm "
        "ON instruments USING gin (symbol gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_instruments_name_trgm "
        "ON instruments USING gin (name gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_instruments_name_trgm")
    op.execute("DROP INDEX IF EXISTS ix_instruments_symbol_trgm")
    # Deliberately leaves the pg_trgm extension in place -- other objects may come to depend on
    # it, and a bare `CREATE EXTENSION` is cheap to re-run, so dropping it here would be a
    # gratuitous foot-gun with no real benefit.
