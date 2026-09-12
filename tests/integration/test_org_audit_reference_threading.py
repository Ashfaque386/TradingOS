"""spec 002 US11 (T049/T050/T053): `events.emit(..., audited=True)` now returns the real
`AuditLog` id it just wrote, and the three call sites that own a domain row's `audit_reference`
FK (`OrganizationalDecision`, `ResultArtefact`, `Task`) thread it in the same transaction --
closing the "data exists, last write missing" gap the original audit found (the column existed,
nothing ever populated it).
"""

from src.core.db import get_session
from src.models.audit import AuditLog
from src.models.orchestration import OrganizationalDecision, ResultArtefact, Task
from src.orchestration import decisions, task_engine
from src.orchestration.enums import DecisionType, TaskStatus
from tests.orchestration_helpers import cleanup_run, seed_run_with_tasks


def test_record_decision_audit_reference_resolves_to_a_real_matching_audit_log_entry():
    run_id, _ = seed_run_with_tasks([])
    try:
        with get_session() as session:
            from src.models.orchestration import OrganizationRun

            run = session.get(OrganizationRun, run_id)
            assert run is not None
            decision = decisions.record_decision(
                session,
                run,
                decision_type=DecisionType.REQUEST_REVIEW,
                summary="test decision for audit-reference threading",
                reason="verifying T050",
                include_portfolio_inputs=False,
            )
            session.commit()
            decision_id = decision.id

        with get_session() as session:
            row = session.get(OrganizationalDecision, decision_id)
            assert row is not None
            assert row.audit_reference is not None, "must not be left null"
            audit_row = session.get(AuditLog, row.audit_reference)
            assert audit_row is not None, "must resolve to a real AuditLog row, not a dangling id"
            assert audit_row.entity_type == "decision"
            assert audit_row.entity_id == decision_id
    finally:
        cleanup_run(run_id)


def test_a_completed_tasks_audit_reference_resolves_to_a_real_audit_log_entry():
    run_id, keys = seed_run_with_tasks(
        [{"key": "a", "capability": "market_analysis", "assigned_agent": "market_analyst"}]
    )
    try:
        task_engine.run_scheduler_loop(run_id)

        with get_session() as session:
            task = session.get(Task, keys["a"])
            assert task is not None
            assert task.status == TaskStatus.COMPLETED.value
            assert task.audit_reference is not None, "must not be left null after completion"
            audit_row = session.get(AuditLog, task.audit_reference)
            assert audit_row is not None, "must resolve to a real AuditLog row, not a dangling id"
            assert audit_row.entity_id == task.id

            assert task.result_artefact_id is not None
            artefact = session.get(ResultArtefact, task.result_artefact_id)
            assert artefact is not None
            assert artefact.audit_reference is not None, "must not be left null after creation"
            artefact_audit_row = session.get(AuditLog, artefact.audit_reference)
            assert artefact_audit_row is not None
            assert artefact_audit_row.entity_id == artefact.id
    finally:
        cleanup_run(run_id)
