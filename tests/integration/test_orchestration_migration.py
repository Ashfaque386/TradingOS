"""Migration verification for the orchestration_core migration (spec T011).

Asserts the 11 new tables exist, ``PendingPaperApproval`` is usable as a ``strategies.status``
value, and the ``organizational_events`` append-only trigger rejects a raw UPDATE.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from src.core.db import get_session
from src.models.orchestration import OrganizationRun
from src.models.tenant import DEFAULT_TENANT_ID

_NEW_TABLES = [
    "organization_runs",
    "organizational_plans",
    "tasks",
    "task_dependencies",
    "result_artefacts",
    "organizational_decisions",
    "organizational_events",
    "approval_requests",
    "agent_configs",
    "prompt_versions",
    "dataset_freshness_records",
]


def test_all_eleven_new_tables_exist():
    with get_session() as session:
        present = {
            r[0]
            for r in session.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
            )
        }
    missing = [t for t in _NEW_TABLES if t not in present]
    assert not missing, f"missing tables: {missing}"


def test_one_active_prompt_version_partial_index_exists():
    with get_session() as session:
        idx = {
            r[0]
            for r in session.execute(
                text("SELECT indexname FROM pg_indexes WHERE tablename = 'prompt_versions'")
            )
        }
    assert "uq_prompt_version_one_active" in idx


def test_strategies_status_has_no_check_constraint_blocking_pending_paper_approval():
    """`PendingPaperApproval` (20 chars) fits `strategies.status VARCHAR(20)` and there is no
    CHECK constraint on that column in this schema, so the new value is usable without a
    constraint migration (data-model.md section 7 migration note)."""
    with get_session() as session:
        checks = [
            r[0]
            for r in session.execute(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid = 'strategies'::regclass AND contype = 'c'"
                )
            )
        ]
    assert not any(
        "status" in c.lower() for c in checks
    ), f"unexpected CHECK on strategies.status: {checks}"
    assert len("PendingPaperApproval") == 20


def test_organizational_events_rejects_mutation():
    """A raw UPDATE on ``organizational_events`` is rejected -- either by the append-only
    trigger or by the ``REVOKE UPDATE`` on the ``tradingos_app`` role (both are enforced;
    which one fires first depends on the connecting role). Done entirely in one uncommitted
    transaction so nothing is left behind."""
    run_id = uuid.uuid4()
    with get_session() as session:
        session.add(
            OrganizationRun(
                id=run_id,
                tenant_id=uuid.UUID(DEFAULT_TENANT_ID),
                objective="append-only probe",
                source="api",
                status="planning",
                thread_id=f"org-probe-{run_id}",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        session.flush()  # the run must exist before the FK'd event insert
        session.execute(
            text(
                "INSERT INTO organizational_events "
                "(run_id, sequence, event_type, subject_type, payload, occurred_at) "
                "VALUES (:rid, 1, 'probe', 'run', '{}'::jsonb, now())"
            ),
            {"rid": str(run_id)},
        )
        session.flush()
        with pytest.raises(Exception, match="append-only|permission denied"):
            session.execute(
                text(
                    "UPDATE organizational_events SET event_type = 'tampered' "
                    "WHERE run_id = :rid"
                ),
                {"rid": str(run_id)},
            )
        session.rollback()
