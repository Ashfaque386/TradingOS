"""REL-031 (SEC-040) integration tests, against the REAL local `postgres` and `minio` compose
services -- no mocking, matching test_audit_tamper_detection.py's and test_audit_archive.py's own
conventions (see those modules' docstrings for why: this table is real, shared, and permanent;
this bucket is real, WORM, and permanent).

Every live-side write here goes through `write_audit_entry` and is NEVER committed (same
rollback-only discipline as test_audit_tamper_detection.py) -- the row's real `id` (a genuine,
permanently-consumed Postgres sequence value even though the row itself is rolled back) is then
used to archive a deliberately synthetic/wrong copy under that same id. Since the id was never
actually committed to the live table, `run_divergence_check` will never see it as a false positive
in any future, unrelated test run (`live_rows.get(id)` is `None` for an id with no live row) --
this leaves permanent but harmless debris in the WORM bucket, the same accepted tradeoff
test_audit_archive.py's own `_fake_row` (random high ids) already makes.
"""

import random
from datetime import datetime

from sqlalchemy import text

from src.core.audit import recompute_entry_hash, write_audit_entry
from src.core.audit_archive import archive_row, ensure_bucket
from src.core.audit_chain_monitor import run_divergence_check
from src.models.audit import AuditLog
from tests.integration.test_audit_tamper_detection import _owner_session


def test_run_divergence_check_reports_no_divergence_for_a_correctly_archived_row():
    ensure_bucket()
    with _owner_session() as session:
        row = write_audit_entry(
            session,
            actor_type="System",
            actor_id="chain-monitor-test-ok",
            action="TEST_EVENT",
            entity_type="Test",
            after_state={"probe": "ok"},
        )
        archive_row(row)  # a real, correct archived copy of the exact row just written

        report = run_divergence_check(session)

        assert row.id not in report.diverged_ids
        assert row.id not in report.archive_broken_ids
        session.rollback()


def test_run_divergence_check_detects_archive_self_inconsistency():
    ensure_bucket()
    # A synthetic id far outside the real sequence range (same technique as
    # test_audit_archive.py's own _fake_row) -- deliberately never touches the live table at all,
    # isolating this test to the archive-self-consistency check specifically.
    row_id = random.randint(10**9, 2 * 10**9)
    broken_copy = AuditLog(
        id=row_id,
        actor_type="System",
        actor_id="chain-monitor-test-self-inconsistent",
        action="TEST_EVENT",
        entity_type="Test",
        entity_id=None,
        before_state=None,
        after_state={"probe": row_id},
        prompt_snapshot=None,
        ip_address=None,
        created_at=datetime(2026, 1, 1),
        entry_hash="a" * 64,  # NOT the real recomputed hash of the content below -- deliberate
        prev_entry_hash="0" * 64,
    )
    archive_row(broken_copy)

    with _owner_session() as session:
        report = run_divergence_check(session)
        session.rollback()

    assert row_id in report.archive_broken_ids
    assert row_id not in report.diverged_ids  # no live row exists at this id to diverge against


def test_run_divergence_check_detects_a_real_live_vs_archive_divergence():
    ensure_bucket()
    with _owner_session() as session:
        row = write_audit_entry(
            session,
            actor_type="System",
            actor_id="chain-monitor-test-divergence",
            action="TEST_EVENT",
            entity_type="Test",
            after_state={"probe": "original"},
        )

        # A self-consistent archived copy (its own entry_hash IS the real recompute of its own
        # content) but for genuinely different content than the live row actually holds -- proves
        # the divergence check fires independently of the archive-self-consistency check
        # (archive_valid stays True here; only diverged_ids should catch this).
        wrong_after_state = {"probe": "tampered-in-archive"}
        wrong_entry_hash = recompute_entry_hash(
            actor_type=row.actor_type,
            actor_id=row.actor_id,
            action=row.action,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            before_state=row.before_state,
            after_state=wrong_after_state,
            prompt_snapshot=row.prompt_snapshot,
            ip_address=row.ip_address,
            created_at=row.created_at,
            prev_hash=row.prev_entry_hash,
        )
        wrong_copy = AuditLog(
            id=row.id,
            actor_type=row.actor_type,
            actor_id=row.actor_id,
            action=row.action,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            before_state=row.before_state,
            after_state=wrong_after_state,
            prompt_snapshot=row.prompt_snapshot,
            ip_address=row.ip_address,
            created_at=row.created_at,
            entry_hash=wrong_entry_hash,
            prev_entry_hash=row.prev_entry_hash,
        )
        archive_row(wrong_copy)

        report = run_divergence_check(session)

        assert row.id in report.diverged_ids
        assert row.id not in report.archive_broken_ids
        session.rollback()


def test_ok_property_is_false_when_the_live_chain_itself_is_broken():
    """A real, committed-nowhere tamper of the live table (same owner-bypass technique as
    test_audit_tamper_detection.py) must make `report.ok` False even with nothing archived at
    all -- `ok` is the AND of all three checks, not just the divergence check this file otherwise
    focuses on."""
    with _owner_session() as session:
        rows = [
            write_audit_entry(
                session,
                actor_type="System",
                actor_id="chain-monitor-test-live-break",
                action=f"TEST_EVENT_{i}",
                entity_type="Test",
            )
            for i in range(2)
        ]
        tampered_id = rows[1].id

        session.execute(text("SET LOCAL session_replication_role = replica"))
        session.execute(
            text("UPDATE audit_log SET action = 'TAMPERED' WHERE id = :id"), {"id": tampered_id}
        )
        session.expire_all()

        report = run_divergence_check(session)

        assert report.live.valid is False
        assert report.ok is False
        session.rollback()
