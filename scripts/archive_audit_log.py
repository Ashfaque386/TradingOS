"""REL-015 E15.3 (GLH-06, SEC-039): nightly WORM audit archive job.

Real object-store replication of AUDIT_LOG rows older than 24h into a MinIO bucket with Object
Lock (COMPLIANCE mode, ~7yr retention) enabled -- a second, independent immutability layer,
alongside the existing Postgres trigger-based protection (src/models/audit.py, src/core/audit.py)
-- see src/core/audit_archive.py's own module docstring for the full design and why idempotency
is tracked by object existence in the bucket, never by a marker column on the row itself (that
would itself require an UPDATE the Postgres trigger correctly refuses).

REL-081: the real cutoff-query/archive loop now lives in
src/core/audit_archive.py::archive_pending_rows (moved, not duplicated) -- this script is now a
thin CLI wrapper over that same function, which is also what the in-process scheduler job
(src/agents/scheduler.py::run_audit_archive_job) calls. Kept as a manual/CLI escape hatch for
running an on-demand archive pass without going through the API:
    docker exec tradingos-app python scripts/archive_audit_log.py
"""

import sys

from src.core.audit_archive import archive_pending_rows
from src.core.db import get_session


def main() -> int:
    with get_session() as session:
        archived_count, failure_count = archive_pending_rows(session)

    if archived_count == 0 and failure_count == 0:
        print("No pending audit_log rows to archive.")
        return 0

    print(f"Archived {archived_count} pending row(s) to the WORM tier.")
    if failure_count:
        print(f"{failure_count} row(s) FAILED to archive -- see app logs for detail.")
        return 1

    print("All pending rows archived successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
