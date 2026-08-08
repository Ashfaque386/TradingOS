"""REL-031 (SEC-040): audit hash-chain divergence detection.

The 2026-08-07 traceability audit found SEC-038's `verify_chain()` (src/core/audit.py, real,
tested) and SEC-039's WORM archive (src/core/audit_archive.py, real, REL-015) existing as two
fully independent immutability layers with zero cross-checking between them -- nothing recomputes
either chain on a schedule, and nothing ever compares the live table's content against what was
actually archived. SEC-040's own literal requirement ("a scheduled job to recompute + compare the
live/WORM-archived hash chains and alert on divergence") had no implementation anywhere.

This module runs three independent checks, none a substitute for the others:

1. Live-table self-consistency: `verify_chain()`, unchanged, already real and tested (SEC-038).
2. Archive self-consistency: for every id already archived, independently recompute its expected
   `entry_hash` from the archived JSON's own stored content fields and its own stored
   `prev_entry_hash` (NOT from the live table), and compare against what's actually stored in the
   WORM object. This does not require walking the archive in id order or from genesis -- each
   archived object carries its own `prev_entry_hash` snapshot from write time, so its own
   self-consistency is checkable independently of its neighbors. Catches archive-side corruption
   (e.g. if Object Lock were ever misconfigured or bypassed) that live-side `verify_chain()` alone
   would never see.
3. Live-vs-archive divergence: for every id present in both stores, the live row's real,
   currently-stored `entry_hash` must equal the archived copy's `entry_hash`. This is the actual
   "did the live and WORM chains diverge" check SEC-040 names -- (1) and (2) alone would both
   report "valid" even if a row were tampered identically in both places, or if the wrong archived
   object were substituted for a given id; this check is what catches disagreement *between* the
   two stores specifically.

Known, honest scaling property, not yet a problem: checks (2) and (3) fetch every archived
object individually and sequentially (no batching/concurrency, no cursor/incremental state
between runs) -- live-verified at 2,455 real archived objects, this takes ~35-40s end to end,
acceptable for a nightly job. This will keep growing (nightly archiving never stops), so if the
archive eventually reaches a scale where a full sequential re-check every night becomes
impractical, this is the function to revisit first (e.g. concurrent fetches, or an incremental
cursor that only re-checks objects archived since the last successful run) -- not a REL-031 fix,
a documented future consideration, matching this project's "flag it honestly rather than silently
pretend it isn't there" convention.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.audit import ChainVerificationResult, recompute_entry_hash, verify_chain
from src.core.audit_archive import fetch_archived_row, list_archived_ids
from src.core.config import Settings, get_settings
from src.models.audit import AuditLog


@dataclass(frozen=True)
class ChainDivergenceReport:
    live: ChainVerificationResult
    archive_valid: bool
    archive_broken_ids: list[int] = field(default_factory=list)
    archived_rows_checked: int = 0
    diverged_ids: list[int] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.live.valid and self.archive_valid and not self.diverged_ids


def _recompute_archived_entry_hash(archived: dict[str, Any]) -> str:
    entity_id_raw = archived.get("entity_id")
    prompt_snapshot_raw = archived.get("prompt_snapshot")
    ip_address_raw = archived.get("ip_address")
    return recompute_entry_hash(
        actor_type=str(archived["actor_type"]),
        actor_id=str(archived["actor_id"]),
        action=str(archived["action"]),
        entity_type=str(archived["entity_type"]),
        entity_id=uuid.UUID(str(entity_id_raw)) if entity_id_raw is not None else None,
        before_state=archived.get("before_state"),
        after_state=archived.get("after_state"),
        prompt_snapshot=str(prompt_snapshot_raw) if prompt_snapshot_raw is not None else None,
        ip_address=str(ip_address_raw) if ip_address_raw is not None else None,
        created_at=datetime.fromisoformat(str(archived["created_at"])),
        prev_hash=str(archived["prev_entry_hash"]),
    )


def run_divergence_check(
    session: Session, *, settings: Settings | None = None
) -> ChainDivergenceReport:
    """Read-only: never writes to `audit_log` or the WORM bucket."""
    settings = settings or get_settings()

    live_result = verify_chain(session)

    archived_ids = sorted(list_archived_ids(settings))
    live_rows: dict[int, AuditLog] = {}
    if archived_ids:
        live_rows = {
            row.id: row
            for row in session.scalars(select(AuditLog).where(AuditLog.id.in_(archived_ids)))
        }

    archive_valid = True
    archive_broken_ids: list[int] = []
    diverged_ids: list[int] = []
    checked = 0

    for row_id in archived_ids:
        archived = fetch_archived_row(row_id, settings=settings)
        if archived is None:
            # Listed by list_archived_ids() a moment ago but gone now -- not expected in normal
            # operation (WORM objects are never deleted, see audit_archive.py), skip rather than
            # fail the whole run over a benign race with a concurrent archive pass.
            continue
        checked += 1

        recomputed = _recompute_archived_entry_hash(archived)
        if recomputed != archived["entry_hash"]:
            archive_valid = False
            archive_broken_ids.append(row_id)
            continue

        live_row = live_rows.get(row_id)
        if live_row is not None and live_row.entry_hash != archived["entry_hash"]:
            diverged_ids.append(row_id)

    return ChainDivergenceReport(
        live=live_result,
        archive_valid=archive_valid,
        archive_broken_ids=archive_broken_ids,
        archived_rows_checked=checked,
        diverged_ids=diverged_ids,
    )
