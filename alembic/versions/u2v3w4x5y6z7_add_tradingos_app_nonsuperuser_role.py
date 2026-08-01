"""add tradingos_app non-superuser role (REL-014 E14.1, GLH-05, closes SEC-041's owner-bypass gap)

Revision ID: u2v3w4x5y6z7
Revises: t1u2v3w4x5y6
Create Date: 2026-08-01 00:00:00.000000

The b3c4d5e6f7a8 migration's own docstring named the real remaining SEC-041 gap precisely:
"a session connected as the table owner can still issue `ALTER TABLE audit_log DISABLE TRIGGER
audit_log_no_mutation` or `SET session_replication_role = replica`". The root cause is narrower
than "owns this one table": `tradingos` (this environment's only role until now) is the
POSTGRES_USER the official postgres image bootstraps as SUPERUSER -- a superuser bypasses every
permission check Postgres has, including ownership checks on tables it doesn't even own. No
REVOKE/trigger combination can close that; only running the application itself as a genuinely
non-superuser role can.

This migration creates `tradingos_app`: LOGIN, NOSUPERUSER, NOCREATEDB, NOCREATEROLE,
NOREPLICATION, granted the same real DML the application actually needs on every table (so
existing behavior is unchanged) but explicitly narrowed on `audit_log` to SELECT/INSERT only,
matching the grants `tradingos` itself has carried since b3c4d5e6f7a8. `ALTER DEFAULT PRIVILEGES`
is set so every future migration's new tables (created by `tradingos`, which remains the schema
owner) automatically grant to `tradingos_app` too, without a follow-up migration each time.

`write_audit_entry()` (src/core/audit.py) takes an existing `Session` specifically so an audit
write commits atomically with the caller's own state change (e.g. a kill-switch trip) -- moving
audit writes to a *separate* connection/role would break that atomicity guarantee. Making the
application's one and only runtime connection non-superuser closes the bypass without touching
that design: `tradingos_app` (the role every live request now runs as) cannot ALTER TABLE or
disable a trigger on audit_log even from inside the exact same code path that also writes to it,
because Postgres enforces this at the connection/role level, not the SQL-string level.

`tradingos` itself is unchanged (still superuser, still owns everything) and continues to be the
only role Alembic migrations run as -- see the paired `alembic/env.py` change (a new, separate
`MIGRATION_DATABASE_URL`) and `docker-compose.yml` (the app/app-tls/monte-carlo-worker services'
`DATABASE_URL` now points at `tradingos_app` instead). Schema migrations remain a human-triggered
operational action using `tradingos`'s credentials, which are no longer part of the live
application's own runtime attack surface.
"""

import os
from typing import Sequence, Union

from alembic import op

revision: str = "u2v3w4x5y6z7"
down_revision: Union[str, None] = "t1u2v3w4x5y6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Dev-only default, same pattern as scripts/seed_admin_user.py's ADMIN_BOOTSTRAP_PASSWORD --
# override via env var before any real deployment.
_APP_ROLE_PASSWORD = os.environ.get("TRADINGOS_APP_DB_PASSWORD", "tradingos_app_dev_password")


def upgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tradingos_app') THEN
                CREATE ROLE tradingos_app LOGIN PASSWORD '{_APP_ROLE_PASSWORD}'
                    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
            END IF;
        END
        $$;
        """
    )

    op.execute("GRANT CONNECT ON DATABASE tradingos TO tradingos_app")
    op.execute("GRANT USAGE ON SCHEMA public TO tradingos_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO tradingos_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO tradingos_app")
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE tradingos IN SCHEMA public "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO tradingos_app"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE tradingos IN SCHEMA public "
        "GRANT USAGE, SELECT ON SEQUENCES TO tradingos_app"
    )

    # Narrow audit_log specifically -- mirrors the REVOKE UPDATE, DELETE FROM tradingos that
    # b3c4d5e6f7a8 already applied to the owner role itself (SEC-037/SEC-041 defense-in-depth).
    op.execute("REVOKE UPDATE, DELETE ON audit_log FROM tradingos_app")


def downgrade() -> None:
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE tradingos IN SCHEMA public "
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM tradingos_app"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE tradingos IN SCHEMA public "
        "REVOKE USAGE, SELECT ON SEQUENCES FROM tradingos_app"
    )
    op.execute("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM tradingos_app")
    op.execute("REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM tradingos_app")
    op.execute("REVOKE USAGE ON SCHEMA public FROM tradingos_app")
    op.execute("REVOKE CONNECT ON DATABASE tradingos FROM tradingos_app")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tradingos_app') THEN
                DROP OWNED BY tradingos_app;
                DROP ROLE tradingos_app;
            END IF;
        END
        $$;
        """
    )
