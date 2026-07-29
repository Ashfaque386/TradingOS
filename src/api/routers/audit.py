"""Audit query API (REL-006 E6.3, API-068/069/070): the read/export surface for the real,
hash-chained AUDIT_LOG (src/core/audit.py, src/models/audit.py) -- the ReadOnlyAuditor role
(src/core/security.py) has existed since Phase 4's auth pass but had zero endpoints to actually
use before this router.

Allowed roles confirmed against Phase_12_Security_Design.md §2.2's RBAC Permission Matrix
(line 68-81: "Export/download audit logs" = Yes for System Administrator, Yes(read-only) for
Read-Only Auditor, No for Portfolio Manager/Risk Manager/AI CEO Agent) -- not guessed.
"""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from src.api.deps import require_role
from src.core.db import get_session
from src.core.security import ROLE_READ_ONLY_AUDITOR, ROLE_SYSTEM_ADMINISTRATOR
from src.models.audit import AuditLog
from src.models.user import User

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])

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
