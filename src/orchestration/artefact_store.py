"""Typed Result Artefact persistence + provenance (spec T013, data-model.md section 5,
FR-030/FR-031).

Every artefact a run produces is persisted here with full provenance and an explicit
``disposition`` (``consumed`` or ``informational``) -- a run may not complete while any of its
artefacts is undispositioned (SC-004), enforced by ``run_manager``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.orchestration import ResultArtefact
from src.orchestration.artefact_schemas import validate_payload
from src.orchestration.enums import ArtefactCoverage, ArtefactDisposition


def build_provenance(
    *,
    agent: str,
    task_id: uuid.UUID,
    run_id: uuid.UUID,
    model_used: str | None = None,
    provider_used: str | None = None,
    tools_used: list[str] | None = None,
    inputs: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "agent": agent,
        "task_id": str(task_id),
        "run_id": str(run_id),
        "model_used": model_used,
        "provider_used": provider_used,
        "tools_used": tools_used or [],
        "inputs": inputs or [],
        "produced_at": datetime.now(UTC).isoformat(),
    }


def persist_artefact(
    session: Session,
    *,
    run_id: uuid.UUID,
    task_id: uuid.UUID,
    artefact_type: str,
    payload: dict[str, Any],
    provenance: dict[str, Any],
    disposition: ArtefactDisposition,
    coverage: ArtefactCoverage | None = None,
    audit_reference: int | None = None,
) -> ResultArtefact:
    """Validate ``payload`` against its registered schema (FR-030), then insert one artefact
    row. ``version`` increments if the same task re-produces the same artefact type."""
    normalised = validate_payload(artefact_type, payload)
    prior = session.scalars(
        select(ResultArtefact)
        .where(ResultArtefact.task_id == task_id, ResultArtefact.artefact_type == artefact_type)
        .order_by(ResultArtefact.version.desc())
    ).first()
    version = (prior.version + 1) if prior is not None else 1

    row = ResultArtefact(
        run_id=run_id,
        task_id=task_id,
        artefact_type=artefact_type,
        version=version,
        payload=normalised,
        provenance=provenance,
        disposition=disposition.value,
        consumed_by_task_ids=[],
        coverage=coverage.value if coverage is not None else None,
        audit_reference=audit_reference,
        created_at=datetime.now(UTC),
    )
    session.add(row)
    session.flush()
    return row


def mark_consumed(session: Session, *, artefact_id: uuid.UUID, by_task_id: uuid.UUID) -> None:
    """Record that a downstream task ingested this artefact (FR-031)."""
    row = session.get(ResultArtefact, artefact_id)
    if row is None:
        return
    consumers = list(row.consumed_by_task_ids)
    if str(by_task_id) not in consumers:
        consumers.append(str(by_task_id))
        row.consumed_by_task_ids = consumers
    row.disposition = ArtefactDisposition.CONSUMED.value
    session.flush()


def undispositioned_count(session: Session, *, run_id: uuid.UUID) -> int:
    """Number of this run's artefacts with no ``disposition`` -- a run may not `complete` while
    this is > 0 (SC-004)."""
    return len(
        session.scalars(
            select(ResultArtefact.id).where(
                ResultArtefact.run_id == run_id, ResultArtefact.disposition.is_(None)
            )
        ).all()
    )
