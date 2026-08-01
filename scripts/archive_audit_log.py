"""REL-015 E15.3 (GLH-06, SEC-039): nightly WORM audit archive job.

Real object-store replication of AUDIT_LOG rows older than 24h into a MinIO bucket with Object
Lock (COMPLIANCE mode, ~7yr retention) enabled -- a second, independent immutability layer,
alongside the existing Postgres trigger-based protection (src/models/audit.py, src/core/audit.py)
-- see src/core/audit_archive.py's own module docstring for the full design and why idempotency
is tracked by object existence in the bucket, never by a marker column on the row itself (that
would itself require an UPDATE the Postgres trigger correctly refuses).

Run nightly via the "TradingOS Nightly Audit Archive" Windows Scheduled Task
(scripts/windows/archive_audit_log.ps1), the same wrapper pattern already used for
scripts/backup_data_lake.py (REL-015 E15.5).
"""

import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from src.core.audit_archive import archive_row, ensure_bucket, list_archived_ids
from src.core.db import get_session
from src.models.audit import AuditLog

_ARCHIVE_AGE = timedelta(hours=24)


def main() -> int:
    ensure_bucket()

    # AuditLog.created_at is TIMESTAMP WITHOUT TIME ZONE, storing naive-UTC wall-clock values
    # (see src/core/audit.py's _canonical_payload docstring for the same convention) -- comparing
    # against a naive-UTC cutoff, not an aware one, keeps this query correct.
    cutoff = datetime.now(UTC).replace(tzinfo=None) - _ARCHIVE_AGE

    with get_session() as session:
        rows = list(
            session.scalars(
                select(AuditLog).where(AuditLog.created_at < cutoff).order_by(AuditLog.id.asc())
            )
        )

    if not rows:
        print("No audit_log rows older than 24h -- nothing to archive.")
        return 0

    already_archived = list_archived_ids()
    pending = [row for row in rows if row.id not in already_archived]

    if not pending:
        print(f"All {len(rows)} eligible row(s) are already archived.")
        return 0

    failures: list[str] = []
    archived_count = 0
    for row in pending:
        try:
            archive_row(row)
            archived_count += 1
        except Exception as exc:  # noqa: BLE001 -- one row's failure must not stop the rest
            failures.append(f"audit_log id={row.id}: {exc}")

    print(f"Archived {archived_count} of {len(pending)} pending row(s) to the WORM tier.")
    if failures:
        print(f"\n{len(failures)} FAILURE(S):")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("All pending rows archived successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
