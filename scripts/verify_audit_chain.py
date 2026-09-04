"""REL-031 (SEC-040): scheduled audit hash-chain divergence check.

Recomputes the live AUDIT_LOG chain (SEC-038) and the WORM-archived copy (SEC-039), and
cross-checks the two against each other -- see src/core/audit_chain_monitor.py's own module
docstring for what each of the three checks catches and why none is a substitute for the others.
On any divergence, fans out a real alert to every configured channel (Telegram/Discord/Slack,
src/core/ops_alerts.py) reusing the same credentials REL-029 wired for downtime alerting.

REL-081: `_format_alert` moved (unchanged) to
src/core/audit_chain_monitor.py::format_divergence_alert so both this script and the in-process
scheduler job (src/agents/scheduler.py::run_audit_chain_verification_job) send the identical
real message. This script is kept as a manual/CLI escape hatch for an on-demand check:
    docker exec tradingos-app python scripts/verify_audit_chain.py
Read-only: never writes to `audit_log` or the WORM bucket.
"""

import asyncio
import sys

from src.core.audit_chain_monitor import format_divergence_alert, run_divergence_check
from src.core.db import get_session
from src.core.ops_alerts import send_ops_alert


def main() -> int:
    with get_session() as session:
        report = run_divergence_check(session)

    if report.ok:
        print(
            f"Chain OK: live {report.live.rows_checked} row(s), "
            f"archive {report.archived_rows_checked} row(s) checked, no divergence."
        )
        return 0

    message = format_divergence_alert(report)
    print(message)

    failures = asyncio.run(send_ops_alert(message))
    if failures:
        print(f"WARNING: alert delivery failed for: {', '.join(failures)}")

    return 1


if __name__ == "__main__":
    sys.exit(main())
