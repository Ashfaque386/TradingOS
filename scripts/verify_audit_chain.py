"""REL-031 (SEC-040): scheduled audit hash-chain divergence check.

Recomputes the live AUDIT_LOG chain (SEC-038) and the WORM-archived copy (SEC-039), and
cross-checks the two against each other -- see src/core/audit_chain_monitor.py's own module
docstring for what each of the three checks catches and why none is a substitute for the others.
On any divergence, fans out a real alert to every configured channel (Telegram/Discord/Slack,
src/core/ops_alerts.py) reusing the same credentials REL-029 wired for downtime alerting.

Run nightly via the "TradingOS Audit Chain Verification" Windows Scheduled Task
(scripts/windows/verify_audit_chain.ps1), the same wrapper pattern already used for
scripts/archive_audit_log.py (REL-015 E15.3). Read-only: never writes to `audit_log` or the WORM
bucket.
"""

import asyncio
import sys

from src.core.audit_chain_monitor import ChainDivergenceReport, run_divergence_check
from src.core.db import get_session
from src.core.ops_alerts import send_ops_alert


def _format_alert(report: ChainDivergenceReport) -> str:
    lines = ["TradingOS AUDIT CHAIN DIVERGENCE DETECTED (SEC-040)"]
    if not report.live.valid:
        lines.append(f"- Live table chain broken at id={report.live.first_broken_id}")
    if not report.archive_valid:
        lines.append(f"- WORM archive self-consistency broken at id(s)={report.archive_broken_ids}")
    if report.diverged_ids:
        lines.append(f"- Live/archive entry_hash divergence at id(s)={report.diverged_ids}")
    return "\n".join(lines)


def main() -> int:
    with get_session() as session:
        report = run_divergence_check(session)

    if report.ok:
        print(
            f"Chain OK: live {report.live.rows_checked} row(s), "
            f"archive {report.archived_rows_checked} row(s) checked, no divergence."
        )
        return 0

    message = _format_alert(report)
    print(message)

    failures = asyncio.run(send_ops_alert(message))
    if failures:
        print(f"WARNING: alert delivery failed for: {', '.join(failures)}")

    return 1


if __name__ == "__main__":
    sys.exit(main())
