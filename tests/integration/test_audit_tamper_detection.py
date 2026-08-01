"""Tamper-detection integration test (REL-006, exit criterion 1): "A real trade/decision/
kill-switch event produces a real, hash-chain-verified AUDIT_LOG row, with a test proving the
chain breaks detectably if a row is tampered with."

Every test here does its writes/tampering/verification inside ONE session and NEVER commits,
relying on `get_session()`'s implicit rollback-on-close for anything not explicitly committed.
This is deliberate, not an oversight: AuditLog is a real, permanent, hash-chained ledger shared
by the whole test suite (there is no per-test database reset) -- deleting a committed row,
tampered or not, orphans every real row written after it (their stored `prev_entry_hash` would
point at a hash that no longer exists in the table), permanently breaking `verify_chain()` for
every later test run, including tests in other files. Never committing is the only way to
exercise real tampering-detection without corrupting the shared table. `verify_chain()` still
walks the ENTIRE real table (this test's uncommitted rows plus every genuinely-committed
production row) -- it must still report the correct `first_broken_id` for OUR row specifically,
proving the detection is real, not scoped to a synthetic empty table.

Simulating tampering requires bypassing the b3c4d5e6f7a8 migration's own append-only trigger via
`SET LOCAL session_replication_role = replica`. UPDATE 2026-08-01 (REL-014 E14.1, GLH-05): the
app's own runtime connection (`get_session()`, now `tradingos_app`) can no longer do this at
all -- that bypass is exactly what REL-014 closed. `SET LOCAL session_replication_role` requires
superuser, which `tradingos_app` deliberately isn't (see alembic/versions/u2v3w4x5y6z7). The two
tamper-simulation tests below now open a second, separate connection using `tradingos`'s own
credentials (`MIGRATION_DATABASE_URL` -- the schema-owning role, still a superuser, used only
for migrations and this one legitimate test purpose: constructing a tamper that only a genuine
DB owner could still perform) to construct the tamper, then verify detection through the app's
own normal (now-restricted) session -- proving `verify_chain()` still catches a real tamper even
though the app itself can no longer create one. `SET LOCAL` is transaction-scoped and the trigger
fires per-statement regardless of whether the transaction is later committed or rolled back, so
the bypass is still required even though neither connection here ever commits.
"""

import os
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.core.audit import verify_chain, write_audit_entry
from src.core.db import get_session


@contextmanager
def _owner_session():
    """A session bound to the schema-owning `tradingos` role (still a real Postgres superuser)
    instead of the app's own `get_session()` (now `tradingos_app`, non-superuser as of REL-014
    E14.1) -- the only role left that can still bypass the append-only trigger, which is exactly
    what these two tests need to construct a tamper to detect. Everything (write, tamper,
    verify) happens on this one connection/transaction, never committed, matching the module
    docstring's "never persist" guarantee -- swapping which role the session uses doesn't change
    that shape, it only changes whether the bypass is even possible to attempt."""
    url = os.environ.get("MIGRATION_DATABASE_URL")
    assert url, "MIGRATION_DATABASE_URL must be set to run the owner-bypass tamper simulation"
    engine = create_engine(url)
    session = Session(bind=engine)
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        engine.dispose()


def test_normal_role_cannot_update_or_delete_audit_log_rows():
    """SEC-037/041 at the DB level: without the replica-role bypass, the append-only trigger
    fires for the app's normal session and rejects the mutation outright."""
    with get_session() as session:
        row = write_audit_entry(
            session,
            actor_type="System",
            actor_id="tamper-test-trigger",
            action="TEST_EVENT",
            entity_type="Test",
        )
        raised = False
        try:
            session.execute(
                text("UPDATE audit_log SET action = 'TAMPERED' WHERE id = :id"), {"id": row.id}
            )
        except Exception:
            raised = True
        assert raised, "the append-only trigger should have rejected this UPDATE"
        session.rollback()  # never persist -- see module docstring


def test_app_role_cannot_bypass_the_trigger_via_replica_mode():
    """REL-014 E14.1 (GLH-05): the real regression test for the fix itself. Before this release,
    the app's own session ran as `tradingos` (a Postgres superuser) and could disable trigger
    firing for itself via `SET LOCAL session_replication_role = replica` -- exactly the owner-
    bypass gap SEC-041 documented as open. The app now runs as `tradingos_app`, which is not a
    superuser and does not own audit_log, so this must fail with a real permission error rather
    than silently succeeding."""
    with get_session() as session:
        raised = False
        try:
            session.execute(text("SET LOCAL session_replication_role = replica"))
        except Exception:
            raised = True
        assert raised, (
            "the app's own session should no longer be able to set session_replication_role "
            "at all -- if this passes, REL-014's non-superuser role split has regressed"
        )
        session.rollback()


def test_verify_chain_detects_a_tampered_after_state_field():
    with _owner_session() as session:
        rows = [
            write_audit_entry(
                session,
                actor_type="System",
                actor_id="tamper-test-detect",
                action=f"TEST_EVENT_{i}",
                entity_type="Test",
                after_state={"n": i},
            )
            for i in range(3)
        ]
        tampered_id = rows[1].id  # tamper the middle row

        session.execute(text("SET LOCAL session_replication_role = replica"))
        session.execute(
            text("UPDATE audit_log SET after_state = CAST(:new_state AS jsonb) WHERE id = :id"),
            {"new_state": '{"n": 9999}', "id": tampered_id},
        )
        # The raw UPDATE above bypasses the ORM, so the AuditLog instances already loaded into
        # this session's identity map (from write_audit_entry, above) still hold their
        # pre-tamper values -- without expiring them, verify_chain's SELECT would return those
        # stale in-memory objects instead of re-reading the real, now-tampered row.
        session.expire_all()

        result = verify_chain(session)
        assert result.valid is False
        assert result.first_broken_id == tampered_id
        session.rollback()  # never persist -- see module docstring


def test_verify_chain_detects_a_tampered_prev_entry_hash():
    with _owner_session() as session:
        rows = [
            write_audit_entry(
                session,
                actor_type="System",
                actor_id="tamper-test-splice",
                action=f"TEST_EVENT_{i}",
                entity_type="Test",
            )
            for i in range(3)
        ]
        spliced_id = rows[2].id

        session.execute(text("SET LOCAL session_replication_role = replica"))
        session.execute(
            text("UPDATE audit_log SET prev_entry_hash = :fake WHERE id = :id"),
            {"fake": "f" * 64, "id": spliced_id},
        )
        session.expire_all()  # see the sibling test above for why this is needed

        result = verify_chain(session)
        assert result.valid is False
        assert result.first_broken_id == spliced_id
        session.rollback()  # never persist -- see module docstring


def test_verify_chain_passes_when_nothing_was_tampered():
    with get_session() as session:
        write_audit_entry(
            session,
            actor_type="System",
            actor_id="tamper-test-clean",
            action="TEST_EVENT",
            entity_type="Test",
        )

        result = verify_chain(session)
        assert result.valid is True
        session.rollback()  # never persist -- see module docstring
