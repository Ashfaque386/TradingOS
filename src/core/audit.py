"""Immutable AUDIT_LOG write/verify service (DB-014, REL-006 E6.2, BR-05).

Real hash-chain per Phase_12_Security_Design.md SEC-038: each row's `entry_hash` =
SHA256(canonical_payload || prev_entry_hash), where `canonical_payload` is a deterministic
JSON serialization of every content column. Altering any historical row's content invalidates
its own hash and every subsequent row's chain link -- `verify_chain()` re-walks the table and
recomputes to detect that.

DB-level append-only enforcement (a BEFORE UPDATE OR DELETE trigger + REVOKE) lives in the
`b3c4d5e6f7a8_add_audit_log_hash_chain` migration, not here -- this module cannot itself
guarantee immutability, only refuse to help callers violate it (there is no update/delete
function in this module at all, by design). See that migration's docstring and
`src/models/audit.py`'s class docstring for the one known gap (a session connected as the
table owner can still disable the trigger -- not fixable at this layer).

WORM archival (SEC-039): implemented as of REL-015 E15.3 (GLH-06) -- see
src/core/audit_archive.py for the real, independent second immutability layer (MinIO Object
Lock, COMPLIANCE mode) this module's rows are replicated into nightly
(scripts/archive_audit_log.py), on top of -- not instead of -- the Postgres-level protection
described above.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from src.models.audit import AuditLog

GENESIS_PREV_HASH = "0" * 64

# Arbitrary fixed key for pg_advisory_xact_lock (must fit Postgres's signed bigint range,
# +/-2^63) -- scopes the lock to "the audit log chain" specifically, distinct from any other
# advisory lock this codebase might take. The value itself is meaningless, just needs to be
# stable and collision-unlikely.
_CHAIN_LOCK_KEY = 4_915_200_000_001


def _canonical_payload(
    *,
    actor_type: str,
    actor_id: str,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    before_state: dict[str, Any] | None,
    after_state: dict[str, Any] | None,
    prompt_snapshot: str | None,
    ip_address: str | None,
    created_at: datetime,
) -> str:
    # AuditLog.created_at is a TIMESTAMP WITHOUT TIME ZONE column: a value written as an
    # aware datetime (write_audit_entry always passes datetime.now(UTC)) round-trips back from
    # a SELECT as a *naive* datetime whose wall-clock numbers still represent UTC. Normalizing
    # both paths to a naive-UTC isoformat string here (rather than calling .isoformat()
    # directly, which would embed a "+00:00" suffix only on the pre-insert aware object) is
    # what makes write-time and verify-time hashes of the same row agree -- without this, every
    # row would show as "tampered" immediately after being written and re-read, a false
    # positive, not a real detection.
    normalized_created_at = created_at.astimezone(UTC) if created_at.tzinfo else created_at
    fields = {
        "actor_type": actor_type,
        "actor_id": actor_id,
        "action": action,
        "entity_type": entity_type,
        "entity_id": str(entity_id) if entity_id is not None else None,
        "before_state": before_state,
        "after_state": after_state,
        "prompt_snapshot": prompt_snapshot,
        # str()'d explicitly (not left to json.dumps's default=str fallback) so a driver that
        # deserializes INET as ipaddress.IPv4Address on read-back still normalizes to the same
        # string form used at write time (when ip_address was already a plain str).
        "ip_address": str(ip_address) if ip_address is not None else None,
        "created_at": normalized_created_at.replace(tzinfo=None).isoformat(),
    }
    return json.dumps(fields, sort_keys=True, default=str)


def write_audit_entry(
    session: Session,
    *,
    actor_type: Literal["Human", "AI Agent", "System"],
    actor_id: str,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    prompt_snapshot: str | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    """Appends one real, hash-chained AuditLog row. Takes an existing Session (mirrors
    kill_switch_service.trip()'s style) so a caller whose own state change must be atomic with
    the audit write can commit both together; a caller that doesn't care commits right after
    this returns.

    `pg_advisory_xact_lock` serializes concurrent writers (a background LangGraph run thread and
    a FastAPI request thread could otherwise both read the same "last row" and produce two rows
    both claiming the same prev_entry_hash) -- the lock is released automatically at transaction
    end (commit or rollback), no manual unlock call needed.
    """
    session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _CHAIN_LOCK_KEY})

    last_hash = session.execute(
        select(AuditLog.entry_hash).order_by(AuditLog.id.desc()).limit(1)
    ).scalar_one_or_none()
    prev_hash = last_hash if last_hash is not None else GENESIS_PREV_HASH

    created_at = datetime.now(UTC)
    payload = _canonical_payload(
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before_state=before_state,
        after_state=after_state,
        prompt_snapshot=prompt_snapshot,
        ip_address=ip_address,
        created_at=created_at,
    )
    entry_hash = hashlib.sha256((payload + prev_hash).encode("utf-8")).hexdigest()

    row = AuditLog(
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before_state=before_state,
        after_state=after_state,
        prompt_snapshot=prompt_snapshot,
        ip_address=ip_address,
        created_at=created_at,
        entry_hash=entry_hash,
        prev_entry_hash=prev_hash,
    )
    session.add(row)
    session.flush()
    return row


@dataclass(frozen=True)
class ChainVerificationResult:
    valid: bool
    first_broken_id: int | None
    rows_checked: int


def verify_chain(session: Session) -> ChainVerificationResult:
    """SEC-040: re-walks audit_log in id order, recomputing each row's expected hash from its
    own stored content and the previous row's stored entry_hash, and compares against what's
    stored. The first row whose recomputed hash mismatches, OR whose prev_entry_hash doesn't
    match the prior row's entry_hash, is reported as `first_broken_id` -- either a tampered
    payload or a spliced/reordered row breaks the chain the same way."""
    rows = list(session.scalars(select(AuditLog).order_by(AuditLog.id.asc())))

    expected_prev = GENESIS_PREV_HASH
    for row in rows:
        if row.prev_entry_hash != expected_prev:
            return ChainVerificationResult(
                valid=False, first_broken_id=row.id, rows_checked=len(rows)
            )
        payload = _canonical_payload(
            actor_type=row.actor_type,
            actor_id=row.actor_id,
            action=row.action,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            before_state=row.before_state,
            after_state=row.after_state,
            prompt_snapshot=row.prompt_snapshot,
            ip_address=row.ip_address,
            created_at=row.created_at,
        )
        recomputed = hashlib.sha256((payload + expected_prev).encode("utf-8")).hexdigest()
        if recomputed != row.entry_hash:
            return ChainVerificationResult(
                valid=False, first_broken_id=row.id, rows_checked=len(rows)
            )
        expected_prev = row.entry_hash

    return ChainVerificationResult(valid=True, first_broken_id=None, rows_checked=len(rows))
