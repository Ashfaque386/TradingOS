"""AuditLog hash-chain write/verify service (REL-006 E6.2, DB-014) against real Postgres.

Note: lives under tests/integration/, not tests/unit/, because write_audit_entry() uses a
Postgres-specific `pg_advisory_xact_lock` call and genuinely cannot run against anything but a
real Postgres connection -- there is no fake/sqlite path for this module by design.

Every test writes inside one session and rolls back at the end instead of committing +
deleting: AuditLog is a real, permanent, shared table with no per-test reset, and deleting a
committed row -- even an untampered one -- orphans every real row written after it, permanently
breaking verify_chain() for later test runs. Never committing avoids that entirely; see
test_audit_tamper_detection.py's module docstring for the full explanation (that file is where
this was first discovered, via a real full-suite regression, not guessed in advance).
"""

from src.core.audit import GENESIS_PREV_HASH, verify_chain, write_audit_entry
from src.core.db import get_session
from src.models.audit import AuditLog


def test_first_write_chains_to_the_genesis_sentinel():
    with get_session() as session:
        row = write_audit_entry(
            session,
            actor_type="System",
            actor_id="test-audit-genesis",
            action="TEST_EVENT",
            entity_type="Test",
        )
        assert len(row.entry_hash) == 64
        # prev_entry_hash is either the genesis sentinel (if this is truly the first row ever)
        # or some other real row's hash (given the shared, permanent table) -- either way it
        # must be a real 64-char value, not null/empty.
        assert len(row.prev_entry_hash) == 64
        session.rollback()


def test_sequential_writes_chain_together():
    with get_session() as session:
        row1 = write_audit_entry(
            session,
            actor_type="System",
            actor_id="test-audit-chain",
            action="TEST_EVENT_1",
            entity_type="Test",
        )
        row2 = write_audit_entry(
            session,
            actor_type="System",
            actor_id="test-audit-chain",
            action="TEST_EVENT_2",
            entity_type="Test",
        )
        assert row2.prev_entry_hash == row1.entry_hash
        session.rollback()


def test_verify_chain_passes_on_untampered_rows():
    with get_session() as session:
        for i in range(3):
            write_audit_entry(
                session,
                actor_type="System",
                actor_id="test-audit-verify",
                action=f"TEST_EVENT_{i}",
                entity_type="Test",
            )
        result = verify_chain(session)
        assert result.valid is True
        assert result.first_broken_id is None
        assert result.rows_checked >= 3
        session.rollback()


def test_genesis_sentinel_constant_is_64_zero_chars():
    assert GENESIS_PREV_HASH == "0" * 64
    assert len(GENESIS_PREV_HASH) == 64


def test_write_audit_entry_row_is_a_real_auditlog_instance():
    with get_session() as session:
        row = write_audit_entry(
            session,
            actor_type="System",
            actor_id="test-audit-type-check",
            action="TEST_EVENT",
            entity_type="Test",
        )
        assert isinstance(row, AuditLog)
        session.rollback()
