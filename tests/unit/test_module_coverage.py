"""REL-009 E9.5: unit tests for scripts/module_coverage.py's gate logic against synthetic
coverage.json fixtures -- no real pytest/coverage run involved, just the pure gate-decision
function itself. Confirms: (1) a module clearing its real Phase_13 target passes, (2) a module
with a real regression below its own recorded baseline fails with a clear message, (3) a module
that has never had a real baseline measured is reported but NOT gated (this project's own
no-fabricated-readiness rule -- see module_coverage.py's MODULE_TARGETS docstring)."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "module_coverage.py"

_spec = importlib.util.spec_from_file_location("module_coverage", MODULE_PATH)
assert _spec is not None and _spec.loader is not None
module_coverage = importlib.util.module_from_spec(_spec)
# Register in sys.modules *before* exec_module: the `@dataclass` decorator on ModuleTarget
# resolves field types via `sys.modules[cls.__module__]`, which is None (and crashes) if this
# dynamically-loaded module was never registered under its own name.
sys.modules["module_coverage"] = module_coverage
_spec.loader.exec_module(module_coverage)


def _write_coverage_json(tmp_path: Path, files: dict[str, tuple[int, int]]) -> None:
    """`files` maps a filename to (covered_lines, num_statements)."""
    data = {
        "files": {
            name: {"summary": {"covered_lines": covered, "num_statements": total}}
            for name, (covered, total) in files.items()
        }
    }
    (tmp_path / "coverage.json").write_text(json.dumps(data), encoding="utf-8")


def test_module_at_or_above_real_target_passes(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(module_coverage, "COVERAGE_JSON_PATH", tmp_path / "coverage.json")
    monkeypatch.setattr(
        module_coverage,
        "MODULE_TARGETS",
        [module_coverage.ModuleTarget("TEST-999", "Fixture Module", "src/fixture", 0.90, 0.90)],
    )
    _write_coverage_json(tmp_path, {"src/fixture/a.py": (95, 100)})

    module_coverage.check()  # must not raise/exit -- passing modules don't call sys.exit()
    assert "[OK]" in capsys.readouterr().out


def test_module_regressing_below_its_own_baseline_fails(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(module_coverage, "COVERAGE_JSON_PATH", tmp_path / "coverage.json")
    monkeypatch.setattr(
        module_coverage,
        "MODULE_TARGETS",
        [module_coverage.ModuleTarget("TEST-999", "Fixture Module", "src/fixture", 0.90, 0.70)],
    )
    _write_coverage_json(tmp_path, {"src/fixture/a.py": (50, 100)})

    with pytest.raises(SystemExit) as exc:
        module_coverage.check()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "[FAIL]" in out


def test_module_with_no_recorded_baseline_is_reported_but_not_gated(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(module_coverage, "COVERAGE_JSON_PATH", tmp_path / "coverage.json")
    monkeypatch.setattr(
        module_coverage,
        "MODULE_TARGETS",
        [module_coverage.ModuleTarget("TEST-999", "Fixture Module", "src/fixture", 0.90, None)],
    )
    # Deliberately far below the Phase_13 target -- must NOT fail, since no real baseline has
    # ever been recorded for this module (fabricating a gate here would be the exact bug fixed
    # in this file's own module).
    _write_coverage_json(tmp_path, {"src/fixture/a.py": (1, 100)})

    module_coverage.check()  # must not raise/exit -- unmeasured modules aren't gated
    assert "[UNMEASURED]" in capsys.readouterr().out


def test_module_with_no_measured_lines_is_skipped(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(module_coverage, "COVERAGE_JSON_PATH", tmp_path / "coverage.json")
    monkeypatch.setattr(
        module_coverage,
        "MODULE_TARGETS",
        [module_coverage.ModuleTarget("TEST-999", "Fixture Module", "src/nonexistent", 0.90, 0.90)],
    )
    _write_coverage_json(tmp_path, {"src/fixture/a.py": (95, 100)})

    module_coverage.check()  # must not raise/exit -- a module with 0 measured lines is skipped
    assert "no measured lines" in capsys.readouterr().out
