"""Bandit security scan targeting the sandbox execution path (Phase 3 Epic E3.1).

The sandbox's `exec()` usage is intentional and justified inline (`# nosec B102`, see
src/engine/sandbox/runner.py's module docstring for the full reasoning) -- this test asserts
Bandit finds no *other*, unreviewed issues in that module. Bandit always honors `# nosec`
comments (there's no CLI flag to defeat it in the open-source tool), so the "is the suppression
covering something real" check below is a direct source-level check instead of trying to make
Bandit report a suppressed finding.
"""

import json
import subprocess
import sys
from pathlib import Path

SANDBOX_DIR = Path(__file__).resolve().parents[2] / "src" / "engine" / "sandbox"


def test_bandit_reports_no_unreviewed_findings_in_sandbox_module():
    result = subprocess.run(
        [sys.executable, "-m", "bandit", "-r", "src/engine/sandbox", "-f", "json"],
        capture_output=True,
        text=True,
        timeout=60,
    )

    report = json.loads(result.stdout)
    assert (
        report["results"] == []
    ), f"Unreviewed Bandit findings in sandbox module: {report['results']}"


def test_nosec_suppression_is_attached_to_a_real_exec_call():
    """Confirms the `# nosec B102` comment actually sits on an exec() line, not orphaned by a
    later refactor -- a source-level check, since Bandit itself won't report a suppressed line
    for us to inspect."""
    source = (SANDBOX_DIR / "runner.py").read_text(encoding="utf-8")
    nosec_lines = [line for line in source.splitlines() if "# nosec B102" in line]
    assert len(nosec_lines) >= 1, "expected at least one `# nosec B102` comment in runner.py"
    assert all(
        "exec(" in line for line in nosec_lines
    ), f"`# nosec B102` comment found on a line without exec(): {nosec_lines}"
