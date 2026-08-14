"""add tenants table + tenant_id threading through users/accounts/strategies/orders (REL-064, API-015)

Revision ID: w4x5y6z7a8b9
Revises: a1a5d7f7bb58
Create Date: 2026-08-14 00:00:00.000000

Real multi-organization tenancy, not a stub: a genuine `tenants` table with `tenant_id` on
every one of the 4 tables approved for this pass. Done in one migration (add nullable, backfill,
tighten to NOT NULL) since this is a single-environment dev/prod host with no concurrent-write/
zero-downtime constraint (Phase 1 ADR 10) -- matches this project's own simpler migration
precedent (e.g. b4c5d6e7f8a9's identical tighten-after-backfill shape for paper_trades.account_id).

Seeds exactly one default "Primary Tenant" row and backfills every existing users/accounts/
strategies/orders row onto it -- the point is that the existing single-tenant system's behavior
is completely unchanged after this migration: every current lookup still finds the same rows,
now all pointing at this one tenant. Cross-tenant query isolation is NOT retrofitted into every
existing endpoint this pass -- see src/models/tenant.py's own docstring for the explicit scope
boundary.

Each new tenant_id column also gets a real Postgres server_default of the Primary Tenant's id
(not just a Python-side default) -- this codebase's own test suite has dozens of pre-existing
fixtures across many files that construct User/Account/Strategy/Order rows directly via the ORM
without knowing this column exists at all; a server_default means every one of those still
inserts successfully, defaulting onto the same Primary Tenant the migration itself backfilled
everything else onto, rather than requiring every fixture file in the suite to be touched.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "w4x5y6z7a8b9"
down_revision: Union[str, None] = "a1a5d7f7bb58"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TENANT_SCOPED_TABLES = ("users", "accounts", "strategies", "orders")


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )

    # A fixed, well-known UUID rather than a freshly-generated one at migration time -- makes
    # the default tenant's id deterministic and reproducible across every environment this
    # migration ever runs against, not a value only discoverable by querying afterward. Matches
    # src.models.tenant.DEFAULT_TENANT_ID exactly (duplicated as a literal here, not imported --
    # migrations in this codebase never import application model code, so a future model change
    # can never silently break a historical migration).
    default_tenant_id = "00000000-0000-0000-0000-000000000001"
    op.execute(
        f"INSERT INTO tenants (id, name, created_at) "
        f"VALUES ('{default_tenant_id}', 'Primary Tenant', now())"
    )

    for table in _TENANT_SCOPED_TABLES:
        op.add_column(
            table,
            sa.Column(
                "tenant_id",
                postgresql.UUID(as_uuid=True),
                nullable=True,
                server_default=sa.text(f"'{default_tenant_id}'"),
            ),
        )
        op.create_foreign_key(
            f"fk_{table}_tenant_id", table, "tenants", ["tenant_id"], ["id"]
        )
        op.execute(f"UPDATE {table} SET tenant_id = '{default_tenant_id}' WHERE tenant_id IS NULL")
        op.alter_column(table, "tenant_id", nullable=False)
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])


def downgrade() -> None:
    for table in _TENANT_SCOPED_TABLES:
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_constraint(f"fk_{table}_tenant_id", table, type_="foreignkey")
        op.drop_column(table, "tenant_id")

    op.drop_table("tenants")
