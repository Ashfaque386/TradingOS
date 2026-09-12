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


def test_approval_requested_event_is_observable_via_get_events():
    """spec 002 US1 (AC4): `approval.requested` joins `approval.approved`/`rejected` on the event
    bus. This exercises `events.emit()` directly for this event type (the same call
    `src/api/routers/agents.py::_open_paper_approval_request` now makes when
    `ApprovalRequest.run_id is not None`) rather than through that legacy code path itself --
    today, every `ApprovalRequest` that path creates has `run_id=None` (it has no
    `OrganizationRun` to attach to), so the guarded `events.emit()` call added there cannot
    fire in production yet, exactly mirroring the pre-existing identical limitation on
    `approval.approved`/`approval.rejected` in `src/orchestration/approvals.py`. That is a
    real, separate gap (threading a real `OrganizationRun` id into the legacy persistence path)
    outside spec 002 US1's scope; this test proves the event-bus half of AC4 is correct once a
    real `run_id` is available, which is the part US1 actually changed."""
    with get_session() as session:
        run_id = _make_run(session)
        approval_id = uuid.uuid4()
        events.emit(
            session,
            run_id=run_id,
            event_type="approval.requested",
            subject_type="approval",
            subject_id=approval_id,
            payload={"strategy_id": str(uuid.uuid4()), "rationale": "test"},
            audited=False,
        )
        session.commit()

    try:
        with get_session() as session:
            rows = (
                session.query(OrganizationalEvent)
                .filter(OrganizationalEvent.run_id == run_id)
                .filter(OrganizationalEvent.event_type == "approval.requested")
                .all()
            )
            assert len(rows) == 1
            assert rows[0].subject_type == "approval"
            assert rows[0].subject_id == approval_id
    finally:
        cleanup_run(run_id)
