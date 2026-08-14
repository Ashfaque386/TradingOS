"""Audit query API (REL-006 E6.3, API-068/069/070): the read/export surface for the real,
hash-chained AUDIT_LOG (src/core/audit.py, src/models/audit.py) -- the ReadOnlyAuditor role
(src/core/security.py) has existed since Phase 4's auth pass but had zero endpoints to actually
use before this router.

Allowed roles confirmed against Phase_12_Security_Design.md §2.2's RBAC Permission Matrix
(line 68-81: "Export/download audit logs" = Yes for System Administrator, Yes(read-only) for
Read-Only Auditor, No for Portfolio Manager/Risk Manager/AI CEO Agent) -- not guessed.
"""

import csv
import io
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select

from src.api.deps import require_role
from src.core.db import get_session
from src.core.security import ROLE_READ_ONLY_AUDITOR, ROLE_SYSTEM_ADMINISTRATOR
from src.models.audit import AuditLog
from src.models.user import User
from src.observability.metrics import AGENT_RUN_DURATION_SECONDS

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])
observability_router = APIRouter(prefix="/api/v1/observability", tags=["observability"])

_can_read_audit = require_role(
    ROLE_SYSTEM_ADMINISTRATOR, ROLE_READ_ONLY_AUDITOR, audit_denials=True
)


class AuditLogEntry(BaseModel):
    id: int
    actor_type: str
    actor_id: str
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    before_state: dict[str, Any] | None
    after_state: dict[str, Any] | None
    ip_address: str | None
    created_at: datetime
    entry_hash: str
    prev_entry_hash: str


def _to_entry(row: AuditLog) -> AuditLogEntry:
    return AuditLogEntry(
        id=row.id,
        actor_type=row.actor_type,
        actor_id=row.actor_id,
        action=row.action,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        before_state=row.before_state,
        after_state=row.after_state,
        ip_address=str(row.ip_address) if row.ip_address is not None else None,
        created_at=row.created_at,
        entry_hash=row.entry_hash,
        prev_entry_hash=row.prev_entry_hash,
    )


@router.get("/logs", response_model=list[AuditLogEntry])
def list_audit_logs(
    entity_type: str | None = None,
    actor_id: str | None = None,
    limit: int = 100,
    _user: User = Depends(_can_read_audit),
) -> list[AuditLogEntry]:
    """API-068."""
    with get_session() as session:
        stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 1000))
        if entity_type is not None:
            stmt = stmt.where(AuditLog.entity_type == entity_type)
        if actor_id is not None:
            stmt = stmt.where(AuditLog.actor_id == actor_id)
        rows = session.scalars(stmt)
        return [_to_entry(r) for r in rows]


@router.get("/logs/{entry_id}", response_model=AuditLogEntry)
def get_audit_log(entry_id: int, _user: User = Depends(_can_read_audit)) -> AuditLogEntry:
    """API-069."""
    with get_session() as session:
        row = session.get(AuditLog, entry_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Audit log entry not found")
        return _to_entry(row)


class TradeAuditTrace(BaseModel):
    entity_id: uuid.UUID
    entries: list[AuditLogEntry]


@router.get("/trades/{entity_id}/trace", response_model=TradeAuditTrace)
def trace_trade(entity_id: uuid.UUID, _user: User = Depends(_can_read_audit)) -> TradeAuditTrace:
    """API-070: every AuditLog row referencing `entity_id`, ordered chronologically -- e.g. for
    an Order id, every ORDER_PLACED / compliance-block / kill-switch-adjacent entry naming it."""
    with get_session() as session:
        rows = session.scalars(
            select(AuditLog).where(AuditLog.entity_id == entity_id).order_by(AuditLog.created_at)
        )
        return TradeAuditTrace(entity_id=entity_id, entries=[_to_entry(r) for r in rows])


class ActorAuditSummary(BaseModel):
    actor_id: str
    total_entries: int
    action_counts: dict[str, int]
    first_entry_at: datetime
    last_entry_at: datetime


@router.get("/actors/{actor_id}/summary", response_model=ActorAuditSummary)
def actor_summary(actor_id: str, _user: User = Depends(_can_read_audit)) -> ActorAuditSummary:
    """REL-010 E10.8e (API-071). Real aggregate over every AuditLog row for one actor (a user
    email, or an agent node name) -- built from the actual rows, not a fabricated rollup."""
    with get_session() as session:
        rows = list(session.scalars(select(AuditLog).where(AuditLog.actor_id == actor_id)))
        if not rows:
            raise HTTPException(status_code=404, detail="No audit entries for this actor")
        action_counts: dict[str, int] = {}
        for row in rows:
            action_counts[row.action] = action_counts.get(row.action, 0) + 1
        return ActorAuditSummary(
            actor_id=actor_id,
            total_entries=len(rows),
            action_counts=action_counts,
            first_entry_at=min(row.created_at for row in rows),
            last_entry_at=max(row.created_at for row in rows),
        )


_EXPORT_FIELDNAMES = list(AuditLogEntry.model_fields)


@router.get("/export")
def export_audit_logs(
    export_format: Literal["csv", "ndjson"] = "ndjson",
    entity_type: str | None = None,
    limit: int = 1000,
    _user: User = Depends(_can_read_audit),
) -> Response:
    """REL-010 E10.8e (API-072). Real rows straight off the same AuditLog table `/logs` reads --
    this just serializes them as a downloadable CSV/NDJSON file instead of a JSON list body."""
    with get_session() as session:
        stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 10000))
        if entity_type is not None:
            stmt = stmt.where(AuditLog.entity_type == entity_type)
        entries = [_to_entry(r) for r in session.scalars(stmt)]

    if export_format == "csv":
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=_EXPORT_FIELDNAMES)
        writer.writeheader()
        for entry in entries:
            writer.writerow(entry.model_dump(mode="json"))
        return Response(content=buffer.getvalue(), media_type="text/csv")

    ndjson_body = "\n".join(entry.model_dump_json() for entry in entries)
    return Response(content=ndjson_body, media_type="application/x-ndjson")


class AgentRunDurationSummary(BaseModel):
    agent_name: str
    run_count: int
    total_duration_seconds: float
    avg_duration_seconds: float | None


@observability_router.get("/agent-run-durations", response_model=list[AgentRunDurationSummary])
def agent_run_durations(_user: User = Depends(_can_read_audit)) -> list[AgentRunDurationSummary]:
    """REL-010 E10.8e. Not tracked under its own API Traceability row (confirmed 2026-08-14,
    REL-059: no row in the ERDTM's "API Traceability" sheet mentions agent-run durations or a
    histogram wrapper) -- previously mislabeled "API-073" here, which is actually
    `/traces/langsmith/{run_id}` (LangSmith trace URL/detail for an LLM call chain, still No in
    the ERDTM). Thin wrapper over the real, already-scraped
    `tradingos_agent_run_duration_seconds` Histogram (src/observability/metrics.py) for a
    non-Prometheus consumer -- reads the metric's own real `_count`/`_sum` samples, not a
    separate DB query, so this can never drift from what Grafana itself is showing."""
    counts: dict[str, float] = {}
    sums: dict[str, float] = {}
    for metric_family in AGENT_RUN_DURATION_SECONDS.collect():
        for sample in metric_family.samples:
            agent_name = sample.labels.get("agent_name")
            if agent_name is None:
                continue
            if sample.name.endswith("_count"):
                counts[agent_name] = sample.value
            elif sample.name.endswith("_sum"):
                sums[agent_name] = sample.value
    return [
        AgentRunDurationSummary(
            agent_name=name,
            run_count=int(count),
            total_duration_seconds=sums.get(name, 0.0),
            avg_duration_seconds=(sums.get(name, 0.0) / count) if count else None,
        )
        for name, count in sorted(counts.items())
    ]
