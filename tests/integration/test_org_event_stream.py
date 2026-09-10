"""Organisational event emission (spec T016, FR-140..142).

Asserts ``events.emit`` writes an append-only row with a gap-free per-run sequence and, for
``audited=True``, an ``AuditLog`` hash-chain entry. Redis publish is best-effort/at-most-once
(the row is the durable truth) so it is not asserted here.
"""

import uuid
from datetime import UTC, datetime

from src.core.db import get_session
from src.models.audit import AuditLog
from src.models.orchestration import OrganizationalEvent, OrganizationRun
from src.models.tenant import DEFAULT_TENANT_ID
from src.orchestration import events
from tests.orchestration_helpers import cleanup_run


def _make_run(session) -> uuid.UUID:  # type: ignore[no-untyped-def]
    run_id = uuid.uuid4()
    session.add(
        OrganizationRun(
            id=run_id,
            tenant_id=uuid.UUID(DEFAULT_TENANT_ID),
            objective="event probe",
            source="api",
            status="planning",
            thread_id=f"org-evt-{run_id}",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    session.flush()
    return run_id


def test_emit_writes_gapfree_rows_and_an_audit_entry_when_audited():
    with get_session() as session:
        run_id = _make_run(session)
        events.emit(
            session,
            run_id=run_id,
            event_type="organization.plan.created",
            subject_type="plan",
            subject_id=uuid.uuid4(),
            payload={"task_count": 3},
            audited=True,
        )
        events.emit(
            session,
            run_id=run_id,
            event_type="task.ready",
            subject_type="task",
            payload={},
            audited=False,
        )
        session.commit()

    try:
        with get_session() as session:
            rows = (
                session.query(OrganizationalEvent)
                .filter(OrganizationalEvent.run_id == run_id)
                .order_by(OrganizationalEvent.sequence)
                .all()
            )
            assert [r.sequence for r in rows] == [1, 2]
            assert rows[0].event_type == "organization.plan.created"
            assert rows[0].payload == {"task_count": 3}

            audits = (
                session.query(AuditLog)
                .filter(AuditLog.action == "ORG_EVENT_ORGANIZATION_PLAN_CREATED")
                .all()
            )
            assert len(audits) >= 1
    finally:
        cleanup_run(run_id)
