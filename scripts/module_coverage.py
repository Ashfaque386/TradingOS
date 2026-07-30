"""REL-009 E9.5: real per-module coverage gate, mapped to Phase_13_Testing_Strategy.md's own
§2 Coverage Targets table (TEST-001..009). Two entry points:

  `python scripts/module_coverage.py measure` -- runs the real suite once with coverage, prints
  each module's real, current line-coverage % next to its Phase_13 target. Use this to establish
  or refresh the `CURRENT_BASELINE` values below when a module's coverage genuinely improves.

  `python scripts/module_coverage.py check` -- the real CI gate (ci.yml calls this after pytest
  has already produced coverage.json): for a module whose CURRENT_BASELINE already meets or
  exceeds its Phase_13 target, the gate IS that real target (matching the design doc exactly);
  for a module still below target, the gate is its own last-measured baseline (regression-only)
  -- never silently lowering the documented target, never fabricating an instant-red gate for a
  module nobody has ever measured against it before. Exits non-zero (and prints the exact
  regressing module + real numbers) on any real regression.

TEST-007 (Agent Orchestrator) is deliberately NOT gated here -- Phase_13 §2 states its own metric
is "LangSmith eval pass-rate, not raw coverage" (>=95% golden-dataset pass rate), a metric this
script has no way to compute; gating `src/agents` on line coverage would silently substitute a
metric the design doc explicitly said not to use. TEST-008 (Frontend) is also excluded -- it's
TypeScript/React, entirely outside this Python coverage.py run.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
COVERAGE_JSON_PATH = REPO_ROOT / "coverage.json"


@dataclass(frozen=True)
class ModuleTarget:
    test_id: str
    label: str
    path_prefix: str
    phase13_target: float  # fraction, e.g. 0.90 for ">90%"
    current_baseline: float | None  # last real measured %, or None if never measured -- see below


# REL-009 E9.5: CURRENT_BASELINE values below are real, measured line-coverage fractions from
# the first-ever genuinely complete full-suite run against this host (2026-07-31,
# `docker compose exec app pytest --cov=src --cov-report=json -q`, 513 passed / 5 skipped / 5
# failed -- all 5 failures pre-existing and environmental: 4 real Zerodha Kite Connect 403s
# (expired daily access token) + 1 real Qdrant-collection data-hygiene flake in
# test_rag_pipeline_e2e.py, neither related to coverage). Every prior attempt this release
# crashed Docker Desktop's memory-constrained VM before finishing (see REL-009's own session
# notes) -- this run finally completed after REL-008's ML/RL platform (torch/lightgbm/mlflow/
# onnxruntime/gymnasium/stable-baselines3) was removed, which was the dominant cause. Computed
# directly from that run's real per-file coverage.json breakdown, summed by real line counts
# (not an average of file percentages) to match _module_coverage()'s own aggregation. Refresh by
# re-running `measure` and pasting the new numbers in -- never hand-edit to a guessed value.
MODULE_TARGETS: list[ModuleTarget] = [
    ModuleTarget("TEST-001", "Trading & Backtesting Engine", "src/engine/backtest", 0.90, 0.9793),
    ModuleTarget("TEST-002", "Risk Manager (Kill Switch)", "src/engine/risk", 1.00, 0.9909),
    ModuleTarget("TEST-003", "Broker Integration Layer", "src/brokers", 0.90, 0.9570),
    ModuleTarget("TEST-004", "API Layer", "src/api", 0.85, 0.7834),
    ModuleTarget("TEST-005", "Market Data Engine", "src/data", 0.85, 0.5707),
    # TEST-006 (Machine Learning Layer, src/ml) removed 2026-07-30 -- the whole ML/RL platform
    # (Phase 5) was disabled pending a host resource upgrade, and src/ml/ no longer exists. Re-add
    # when Phase 5 is re-implemented.
    ModuleTarget("TEST-009", "Observability & Audit", "src/observability", 0.80, 0.9142),
]


def _run_pytest_with_coverage() -> None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--cov=src",
            "--cov-report=json",
            "-q",
        ],
        cwd=REPO_ROOT,
        check=False,  # a real test failure shouldn't hide the coverage numbers this exists for
    )


def _module_coverage(coverage_data: dict[str, Any], path_prefix: str) -> tuple[float, int]:
    """Real line-coverage fraction for every file under `path_prefix`, aggregated by real line
    counts (not an average-of-file-percentages, which would misweight small files)."""
    covered = 0
    total = 0
    for filename, file_data in coverage_data.get("files", {}).items():
        normalized = filename.replace("\\", "/")
        if not normalized.startswith(path_prefix + "/") and normalized != path_prefix:
            continue
        summary = file_data["summary"]
        covered += summary["covered_lines"]
        total += summary["num_statements"]
    if total == 0:
        return 0.0, 0
    return covered / total, total


def _load_coverage_json() -> dict[str, Any]:
    if not COVERAGE_JSON_PATH.exists():
        print(
            f"error: {COVERAGE_JSON_PATH} does not exist -- run pytest with "
            "--cov=src --cov-report=json first",
            file=sys.stderr,
        )
        sys.exit(2)
    result: dict[str, Any] = json.loads(COVERAGE_JSON_PATH.read_text(encoding="utf-8"))
    return result


def measure() -> None:
    _run_pytest_with_coverage()
    data = _load_coverage_json()
    print(f"{'Module':<32} {'Real %':>8} {'Target':>8} {'Lines':>8}")
    for m in MODULE_TARGETS:
        pct, lines = _module_coverage(data, m.path_prefix)
        print(f"{m.label:<32} {pct * 100:>7.1f}% {m.phase13_target * 100:>7.0f}% {lines:>8}")


def check() -> None:
    data = _load_coverage_json()
    failures: list[str] = []
    for m in MODULE_TARGETS:
        pct, lines = _module_coverage(data, m.path_prefix)
        if lines == 0:
            print(f"warning: {m.label} ({m.path_prefix}) has no measured lines -- skipping gate")
            continue
        if m.current_baseline is None:
            # No real baseline has ever been measured for this module (see MODULE_TARGETS'
            # own comment) -- gating on phase13_target here would be an instant, fabricated
            # failure the first time this ever runs, and gating on a guessed baseline would be
            # fabricated data. Report the real number so it's visible, but don't enforce yet.
            print(
                f"[UNMEASURED] {m.label} ({m.test_id}): {pct * 100:.1f}% real coverage "
                f"(Phase_13 target {m.phase13_target * 100:.0f}%) -- no baseline recorded yet, "
                "not gated this run"
            )
            continue
        # Real target only where the real baseline already clears it; otherwise a regression-only
        # gate against the last real measurement -- see this module's own docstring.
        gate = m.phase13_target if m.current_baseline >= m.phase13_target else m.current_baseline
        status = "OK" if pct >= gate else "FAIL"
        print(
            f"[{status}] {m.label} ({m.test_id}): {pct * 100:.1f}% "
            f"(gate {gate * 100:.1f}%, Phase_13 target {m.phase13_target * 100:.0f}%)"
        )
        if pct < gate:
            failures.append(
                f"{m.label}: {pct * 100:.1f}% dropped below its gate of {gate * 100:.1f}%"
            )
    if failures:
        print("\nCoverage gate FAILED:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        sys.exit(1)
    print(
        "\nAll gated module coverage checks passed (see UNMEASURED lines above for modules "
        "not yet enforced)."
    )


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("measure", "check"):
        print(f"usage: {sys.argv[0]} {{measure|check}}", file=sys.stderr)
        sys.exit(2)
    {"measure": measure, "check": check}[sys.argv[1]]()
