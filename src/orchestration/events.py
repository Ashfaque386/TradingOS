"""Organisational event emission (spec T014, contracts/events.md, FR-140/141/142).

One ``emit()`` call does three things atomically-with-the-caller:
  1. inserts an append-only ``organizational_events`` row with a gap-free per-run ``sequence``
     (the DB trigger from the migration rejects any later UPDATE/DELETE),
  2. publishes a compact JSON envelope to the Redis ``organization:events`` channel for the
     live console (best-effort; the row is the durable truth),
  3. for ``audited=True``, writes an ``AuditLog`` hash-chain entry via the existing writer.

The console treats the Redis stream as a hint to refetch/patch, never the sole source -- exactly
the tick-relay philosophy already used elsewhere.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.core.audit import write_audit_entry
from src.memory.redis_client import get_redis_client
from src.models.orchestration import OrganizationalEvent

ORGANIZATION_EVENT_CHANNEL = "organization:events"
logger = structlog.get_logger(__name__)


def _next_sequence(session: Session, run_id: uuid.UUID) -> int:
    current = session.scalar(
        select(func.coalesce(func.max(OrganizationalEvent.sequence), 0)).where(
            OrganizationalEvent.run_id == run_id
        )
    )
    return int(current or 0) + 1


def emit(
    session: Session,
    *,
    run_id: uuid.UUID,
    event_type: str,
    subject_type: str,
    subject_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
    audited: bool = False,
) -> OrganizationalEvent:
    """Insert the event row + publish to Redis (+ optional audit). The caller owns the
    transaction; this ``flush()``es but does not ``commit()`` so the event and the caller's own
    state change land together (data-model.md section 8)."""
    now = datetime.now(UTC)
    sequence = _next_sequence(session, run_id)
    row = OrganizationalEvent(
        run_id=run_id,
        sequence=sequence,
        event_type=event_type,
        subject_type=subject_type,
        subject_id=subject_id,
        payload=payload or {},
        occurred_at=now,
    )
    session.add(row)
    session.flush()

    if audited:
        write_audit_entry(
            session,
            actor_type=(
                "AI Agent" if event_type.startswith(("ceo.", "task.", "agent.")) else "System"
            ),
            actor_id="organization",
            action=f"ORG_EVENT_{event_type.upper().replace('.', '_')}",
            entity_type=subject_type,
            entity_id=subject_id,
            after_state=payload or {},
        )

    envelope = json.dumps(
        {
            "run_id": str(run_id),
            "sequence": sequence,
            "event_type": event_type,
            "subject_type": subject_type,
            "subject_id": str(subject_id) if subject_id else None,
            "payload": payload or {},
            "occurred_at": now.isoformat(),
        }
    )
    try:
        get_redis_client().publish(ORGANIZATION_EVENT_CHANNEL, envelope)
    except (
        Exception
    ) as exc:  # noqa: BLE001 -- a display-feed hiccup must never fail a real state change
        logger.warning("organization_event_publish_failed", event_type=event_type, error=str(exc))

    return row
