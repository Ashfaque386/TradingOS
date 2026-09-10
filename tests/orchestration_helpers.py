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

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


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
