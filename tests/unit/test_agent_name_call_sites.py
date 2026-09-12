"""spec 002 US2 / SC-002: every real `complete()` call site must pass `agent_name=`, so a
per-agent `CUSTOM` provider/model override (`src/orchestration/agent_config.py`) actually
affects that call, rather than being recorded-but-inert. This is a static, repo-wide check --
not a one-time spot check -- so a new node added later without `agent_name=` fails CI
immediately instead of silently reintroducing the gap this feature closed.
"""

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCANNED_PATHS = [
    _REPO_ROOT / "src" / "agents" / "nodes",
    _REPO_ROOT / "src" / "orchestration" / "planner.py",
    _REPO_ROOT / "src" / "orchestration" / "agent_invoker.py",
]


def _complete_call_sites(path: Path) -> list[ast.Call]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    calls = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "complete"
        ):
            calls.append(node)
    return calls


def _files_to_scan() -> list[Path]:
    files: list[Path] = []
    for target in _SCANNED_PATHS:
        if target.is_dir():
            files.extend(sorted(target.glob("*.py")))
        elif target.is_file():
            files.append(target)
    return files


def test_every_complete_call_site_passes_agent_name() -> None:
    files = _files_to_scan()
    assert len(files) >= 3, f"expected to find agent node/orchestration files, found {files}"

    missing: list[str] = []
    total_calls = 0
    for path in files:
        for call in _complete_call_sites(path):
            total_calls += 1
            has_agent_name = any(kw.arg == "agent_name" for kw in call.keywords)
            if not has_agent_name:
                missing.append(f"{path.relative_to(_REPO_ROOT)}:{call.lineno}")

    assert total_calls > 0, "expected to find at least one complete() call site to check"
    assert not missing, (
        "the following complete() call sites do not pass agent_name= -- a CUSTOM "
        f"provider/model override for that agent would be silently ignored: {missing}"
    )
