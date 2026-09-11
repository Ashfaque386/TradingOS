"""Shared helpers for the CEO-led organisation layer tests (spec 001-ceo-led-trading-org).

``owner_session`` connects as the schema-owning ``tradingos`` role (via
``MIGRATION_DATABASE_URL``) -- the only role that can DELETE from ``organizational_events``
(the app role ``tradingos_app`` has ``REVOKE UPDATE, DELETE`` + the append-only trigger). Used
only for test teardown, mirroring ``test_audit_tamper_detection.py``'s pattern.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.core.db import get_session
from src.models.orchestration import (
    OrganizationalPlan,
    OrganizationRun,
    Task,
    TaskDependency,
)
from src.models.tenant import DEFAULT_TENANT_ID
from src.orchestration.capability_registry import is_concurrency_safe


def seed_run_with_tasks(
    task_specs: list[dict[str, object]],
) -> tuple[uuid.UUID, dict[str, uuid.UUID]]:
    """Insert an OrganizationRun + OrganizationalPlan + Task rows (status ``planned``) directly,
    bypassing the LLM planner. ``task_specs`` items: ``{key, capability, assigned_agent,
    expected_output?, depends_on?}``. Returns ``(run_id, {key: task_id})``."""
    now = datetime.now(UTC)
    run_id = uuid.uuid4()
    with get_session() as session:
        run = OrganizationRun(
            id=run_id,
            tenant_id=uuid.UUID(DEFAULT_TENANT_ID),
            objective="seeded test run",
            source="api",
            status="planning",
            thread_id=f"org-seed-{run_id}",
            created_at=now,
            updated_at=now,
        )
        session.add(run)
        session.flush()
        plan = OrganizationalPlan(
            run_id=run_id,
            objective_classification="test",
            departments=[],
            constraints={},
            safety_requirements={},
            approval_required=False,
            created_at=now,
        )
        session.add(plan)
        session.flush()
        run.plan_id = plan.id

        key_to_id: dict[str, uuid.UUID] = {}
        for spec in task_specs:
            cap = str(spec["capability"])
            task = Task(
                plan_id=plan.id,
                run_id=run_id,
                tenant_id=uuid.UUID(DEFAULT_TENANT_ID),
                objective=f"task {spec['key']}",
                assigned_agent=str(spec["assigned_agent"]),
                assigned_by="ceo_agent",
                capability=cap,
                priority=5,
                dependency_policy="all",
                required_inputs=[],
                received_inputs=[],
                required_datasets=spec.get("required_datasets") or None,  # type: ignore[arg-type]
                expected_output=str(spec.get("expected_output", "AdHocAnalysis")),
                status="planned",
                is_concurrency_safe=is_concurrency_safe(cap),
                timeout_seconds=int(spec.get("timeout_seconds") or 300),  # type: ignore[arg-type]
                correlation_id=run.thread_id,
                created_at=now,
            )
            session.add(task)
            session.flush()
            key_to_id[str(spec["key"])] = task.id

        for spec in task_specs:
            for dep_key in spec.get("depends_on", []):  # type: ignore[union-attr]
                session.add(
                    TaskDependency(
                        plan_id=plan.id,
                        dependent_task_id=key_to_id[str(spec["key"])],
                        prerequisite_task_id=key_to_id[str(dep_key)],
                        required_artefact_type="Artefact",
                        policy="hard",
                        state="unsatisfied",
                        created_at=now,
                    )
                )
        session.commit()
    return run_id, key_to_id


@contextmanager
def owner_session() -> Iterator[Session]:
    url = os.environ.get("MIGRATION_DATABASE_URL")
    assert url, "MIGRATION_DATABASE_URL must be set for organisation-layer test teardown"
    engine = create_engine(url)
    session = Session(bind=engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def cleanup_run(run_id: uuid.UUID) -> None:
    """Delete a run and everything hanging off it, in FK-safe order. Runs as the schema-owning
    role with ``session_replication_role = replica`` so the ``organizational_events`` /
    ``audit_log`` append-only triggers are bypassed for teardown only (same technique as
    ``test_audit_tamper_detection.py``)."""
    rid = str(run_id)
    with owner_session() as session:
        session.execute(text("SET session_replication_role = replica"))
        for stmt in (
            "DELETE FROM task_dependencies WHERE plan_id IN "
            "(SELECT id FROM organizational_plans WHERE run_id = :rid)",
            "DELETE FROM result_artefacts WHERE run_id = :rid",
            "DELETE FROM tasks WHERE run_id = :rid",
            "DELETE FROM approval_requests WHERE run_id = :rid",
            "DELETE FROM organizational_decisions WHERE run_id = :rid",
            "DELETE FROM organizational_events WHERE run_id = :rid",
            "UPDATE organization_runs SET plan_id = NULL WHERE id = :rid",
            "DELETE FROM organizational_plans WHERE run_id = :rid",
            "DELETE FROM organization_runs WHERE id = :rid",
        ):
            session.execute(text(stmt), {"rid": rid})
        session.execute(text("SET session_replication_role = DEFAULT"))
        session.commit()
