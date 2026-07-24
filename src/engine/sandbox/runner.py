"""Subprocess-based execution sandbox (Phase 3 Epic E3.1).

Runs AI-generated strategy code (expected to define `run_backtest(data, config) -> dict`) in a
separate, resource-limited, network-disabled subprocess with a restricted builtins set -- NOT
a full per-execution Docker container. Per the project's explicit 2026-07 decision, mounting
the Docker socket into the app container (Docker-in-Docker) to spin up a container per
execution was rejected as its own security anti-pattern (a compromised app container would get
root-equivalent host access) for a project that isn't executing anything with real money yet
(live trading is Phase 4, gated behind human approval per Business Rule 3).

This is defense-in-depth, not a hermetic security boundary: process isolation + a CPU-time
resource limit + a wall-clock timeout backstop + a monkey-patched `socket` module (blocks the
vast majority of accidental or malicious network calls, since urllib/requests/etc. all
ultimately open a socket) + running strictly after the AST-level ban-list
(src/agents/tools/skills.py's static_safety_check) has already rejected the code. It is not
equivalent to a container or VM boundary, and that's stated here plainly rather than
overclaimed.

Deliberately NOT enforced: a hard virtual-memory ulimit (RLIMIT_AS/RLIMIT_DATA). Polars and
VectorBT's Rust/jemalloc-based allocators reserve large virtual address ranges up front as
normal behavior, independent of actual data size -- a hard ulimit low enough to catch a
runaway strategy also kills every legitimate run with "background thread creation failed" /
"memory allocation failed" errors (verified empirically while building this sandbox). Peak
memory is reported for observability instead of enforced as a hard cap; CPU time and
wall-clock are the real enforced boundaries.
"""

import json
import resource
import subprocess  # nosec B404 -- running the sandboxed subprocess IS this module's purpose
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT_SECONDS = 10.0

_RUNNER_TEMPLATE = """
import json
import resource
import socket
import sys

# --- Resource limit: CPU time, enforced by the OS, not just Python. See module docstring for
# why a virtual-memory ulimit is deliberately not also set here. ---
resource.setrlimit(resource.RLIMIT_CPU, ({cpu_seconds}, {cpu_seconds}))

# --- Network block: monkey-patch socket.socket before the strategy code ever imports it. ---
class _BlockedSocket:
    def __init__(self, *args, **kwargs):
        raise OSError("Network access is disabled inside the sandbox")


socket.socket = _BlockedSocket

# --- Load the dummy OHLCV dataset the strategy will run against. ---
import polars as pl

data = pl.read_parquet({data_path!r})

result = {{"passed": False, "portfolio_summary": None, "error": None}}
try:
    namespace: dict = {{"__name__": "__sandboxed_strategy__"}}
    # nosec B102: exec() is the sandbox's entire purpose (running AI-generated strategy code)
    # -- it happens only inside this already-isolated subprocess, after static_safety_check has
    # rejected banned calls/imports, with sockets blocked and CPU-time capped. See module
    # docstring for the full defense-in-depth reasoning.
    exec(compile({code!r}, "<sandboxed_strategy>", "exec"), namespace)  # nosec B102
    run_backtest = namespace.get("run_backtest")
    if run_backtest is None:
        raise ValueError("strategy code did not define run_backtest(data, config)")
    config = json.loads({config_json!r})
    portfolio = run_backtest(data, config)
    if not isinstance(portfolio, dict):
        raise TypeError(f"run_backtest must return a dict, got {{type(portfolio).__name__}}")
    result["passed"] = True
    result["portfolio_summary"] = portfolio
except BaseException as exc:  # noqa: BLE001 - must report every failure, not crash silently
    result["error"] = f"{{type(exc).__name__}}: {{exc}}"

sys.stdout.write(json.dumps(result))
"""


@dataclass(frozen=True)
class SandboxResult:
    passed: bool
    portfolio_summary: dict[str, Any] | None
    error: str | None
    duration_seconds: float
    peak_memory_mb: float | None = (
        None  # observability only -- not an enforced limit; see docstring
    )


def _dummy_ohlcv_parquet(tmpdir: Path) -> Path:
    import polars as pl

    path = tmpdir / "dummy_ohlcv.parquet"
    dates = pl.date_range(
        __import__("datetime").date(2024, 1, 1),
        __import__("datetime").date(2024, 3, 1),
        "1d",
        eager=True,
    )
    n = len(dates)
    df = pl.DataFrame(
        {
            "symbol": ["DUMMY"] * n,
            "date": dates,
            "open": [100.0 + i * 0.1 for i in range(n)],
            "high": [101.0 + i * 0.1 for i in range(n)],
            "low": [99.0 + i * 0.1 for i in range(n)],
            "close": [100.5 + i * 0.1 for i in range(n)],
            "volume": [10000] * n,
        }
    )
    df.write_parquet(path)
    return path


def execute_in_sandbox(
    code: str,
    config: dict[str, Any] | None = None,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    data_path: Path | None = None,
) -> SandboxResult:
    """Runs `code` (expected to define run_backtest(data, config)) in an isolated subprocess.

    `data_path` defaults to a small synthetic OHLCV dataset (validation use, Phase 3 E3.1: does
    the code run at all). Passing a real data-lake Parquet path (Phase 4 E4.3's real backtest
    trigger, src/engine/sandbox/backtest_runner.py) runs the exact same code against real
    historical prices through the exact same sandbox boundary -- no separate, less-audited
    execution path for "real" vs. "validation" runs. Returns SandboxResult -- never raises for
    strategy-code errors; only raises if the sandbox harness itself is misconfigured."""
    config = config or {}
    start = time.perf_counter()
    rusage_before = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss

    with tempfile.TemporaryDirectory() as tmpdir_str:
        tmpdir = Path(tmpdir_str)
        if data_path is None:
            data_path = _dummy_ohlcv_parquet(tmpdir)
        runner_script = _RUNNER_TEMPLATE.format(
            cpu_seconds=int(timeout),
            data_path=str(data_path),
            code=code,
            config_json=json.dumps(config),
        )
        script_path = tmpdir / "sandbox_runner.py"
        script_path.write_text(runner_script, encoding="utf-8")

        try:
            # nosec B603 -- no shell=True, args are a fixed list: the trusted interpreter path
            # (sys.executable) plus a tempfile path we just wrote ourselves. The untrusted part
            # (the strategy code) is data written to that file, not a shell/argv string, so
            # there's no shell-injection surface here.
            proc = subprocess.run(  # nosec B603
                [sys.executable, str(script_path)],
                capture_output=True,
                text=True,
                timeout=timeout + 2.0,  # wall-clock grace period beyond the CPU rlimit
                cwd=str(tmpdir),
                env={"PATH": "/usr/bin:/bin"},  # minimal env: no proxies, no credentials leak
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(
                passed=False,
                portfolio_summary=None,
                error=f"sandbox execution exceeded {timeout}s wall-clock timeout",
                duration_seconds=time.perf_counter() - start,
            )

        duration = time.perf_counter() - start
        # ru_maxrss is cumulative across all children ever reaped by this process, in KB on Linux.
        peak_memory_mb = (
            resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss - rusage_before
        ) / 1024

        if proc.returncode != 0 and not proc.stdout.strip():
            return SandboxResult(
                passed=False,
                portfolio_summary=None,
                error=f"sandbox process exited {proc.returncode}: {proc.stderr[-2000:]}",
                duration_seconds=duration,
                peak_memory_mb=peak_memory_mb,
            )

        try:
            parsed = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return SandboxResult(
                passed=False,
                portfolio_summary=None,
                error=(
                    f"sandbox produced non-JSON output: "
                    f"{proc.stdout[-500:]!r} / {proc.stderr[-500:]!r}"
                ),
                duration_seconds=duration,
                peak_memory_mb=peak_memory_mb,
            )

        return SandboxResult(
            passed=parsed["passed"],
            portfolio_summary=parsed["portfolio_summary"],
            error=parsed["error"],
            duration_seconds=duration,
            peak_memory_mb=peak_memory_mb,
        )
