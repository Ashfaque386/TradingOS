"""REL-032 (NFR-01): a small pool of persistent, warm sandbox worker subprocesses.

Real, empirically-measured problem (Phase_14 REL-028): `execute_in_sandbox()` (runner.py) spawns
a brand-new Python interpreter for every single call -- every run pays the FULL cost of importing
`polars`/`vectorbt` (which itself eagerly numba-JIT-compiles dozens of vectorbt's own internal
kernels at import time, independent of any specific strategy) plus first-call JIT specialization
for whatever numba kernel variants that call's specific inputs hit. Measured directly before
writing any of this module, not assumed: a fresh process's first vectorbt-backed backtest call
takes ~9-29s (import + JIT, real variance observed across repeated measurements); every
SUBSEQUENT call in the SAME already-warm process takes ~0.06s -- a >99% reduction, closely
matching REL-028's own real ~20s end-to-end measurement. Also measured and ruled out before
choosing this design: numba's own on-disk JIT cache (`cache=True`, already used by 78 of
vectorbt's own kernels, confirmed by reading vectorbt.portfolio.nb's source) does NOT meaningfully
help across separate fresh processes in this environment -- four repeated fresh-process
measurements with a warm on-disk cache stayed at ~9.5-9.8s, no better than the ~8.8s
cold-disk-cache baseline. This rules out "just enable numba's disk cache" as a lower-risk
alternative to pooling -- the win genuinely requires keeping a process (and its already-imported,
already-JIT-compiled modules) alive across calls, not just caching compiled machine code to disk.

**Real security tradeoff, stated plainly rather than hidden** (matching runner.py's own module
docstring convention): runner.py names PROCESS ISOLATION as this sandbox's core defense-in-depth
layer -- a fresh process per call means no strategy's code can ever affect a later, unrelated
strategy's run. A worker that executes MULTIPLE different (mutually-distrusting, LLM-generated)
strategies across its lifetime necessarily weakens that isolation somewhat. Mitigations, all real
and enforced here, not just claimed:

1. Each call still `exec()`s into a FRESH per-call namespace dict, identical in spirit to
   runner.py's own per-call namespace -- a strategy's own local variables/functions/classes never
   survive to the next call in the same worker. Only the IMPORTED LIBRARY MODULES' own state
   (`polars`/`vectorbt`/`numba`'s compiled kernels -- legitimate performance state, not
   strategy-controlled data) persists between calls.
2. `static_safety_check` (src/agents/tools/skills.py) now additionally bans `setattr` outright
   and bans direct `.`-syntax attribute assignment onto the specific shared library aliases a
   strategy could otherwise use to poison a LATER run in the same worker (`vbt`/`vectorbt`/
   `pl`/`polars`/`pd`/`pandas`/`np`/`numpy`/`numba`) -- a real, new AST rule added specifically
   because pooling makes this a real threat for the first time; it was not one under the old
   fresh-process-per-call model, where any such poisoning died with the process.
3. Every worker is retired (killed, never reused) after `MAX_JOBS_PER_WORKER` real executions --
   bounding the maximum exposure window of any single worker to a small, fixed number of runs,
   not indefinite reuse.
4. `RLIMIT_CPU` is a POSIX process-LIFETIME hard cap, not a per-call budget -- unlike the old
   model (a fresh rlimit set inside every fresh `subprocess.run` call), a worker's rlimit here
   must cover its entire planned lifetime (`MAX_JOBS_PER_WORKER` calls' worth) up front, set once
   at worker startup. Per-call WALL-CLOCK enforcement moves to the pool manager instead: a
   worker that doesn't answer within `timeout + grace` is treated as poisoned or hung and killed
   outright (never reused, never given a second chance), the same fail-closed posture a real
   CPU-limit violation already had.
5. The network block (socket monkeypatch) is unchanged in spirit -- still applied once, still
   process-global, still blocks the same way for every call in that worker's lifetime.

`execute_in_pool()` falls back to the original one-shot `execute_in_sandbox()` (runner.py) if the
pool itself is disabled or fails to start -- a pool failure degrades to "slow but correct," never
to "broken." Only `src/engine/sandbox/backtest_runner.py::run_real_backtest` (the real,
latency-sensitive, NFR-01-measured path) uses this pool; Phase 3's validation-only sandbox calls
(`src/agents/tools/skills.py::ExecuteDryRunSandboxSkill`, small dummy dataset, part of the
LLM code-generation/validation loop) deliberately keep using the unchanged one-shot
`execute_in_sandbox()` -- that path doesn't need this optimization, and changing it would risk
behavior differences in an already well-tested loop for no real benefit.
"""

from __future__ import annotations

import json
import os
import selectors
import subprocess  # nosec B404 -- same justification as runner.py: this module's own purpose
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.core.config import Settings, get_settings
from src.engine.sandbox.runner import DEFAULT_TIMEOUT_SECONDS, SandboxResult, execute_in_sandbox

MAX_JOBS_PER_WORKER = 25
_CPU_SECONDS_PER_JOB_BUDGET = 120  # matches backtest_runner.REAL_BACKTEST_TIMEOUT_SECONDS
_WORKER_ENV = {"PATH": "/usr/bin:/bin"}  # minimal env, same posture as runner.py

_POOL_WORKER_SCRIPT = """
import json
import resource
import socket
import sys

resource.setrlimit(resource.RLIMIT_CPU, ({total_cpu_seconds}, {total_cpu_seconds}))


class _BlockedSocket:
    def __init__(self, *args, **kwargs):
        raise OSError("Network access is disabled inside the sandbox")


socket.socket = _BlockedSocket

# Imported once, here, at worker startup -- this is the whole point of the pool: every call in
# this worker's lifetime reuses this already-imported, already-JIT-warm module.
import polars as pl
import vectorbt as vbt  # noqa: F401

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    job = json.loads(line)
    result = {{"passed": False, "portfolio_summary": None, "error": None}}
    try:
        data = pl.read_parquet(job["data_path"])
        namespace: dict = {{"__name__": "__sandboxed_strategy__"}}
        # nosec B102: exec() is this sandbox's entire purpose, see runner.py's own module
        # docstring for the full reasoning -- unchanged by pooling.
        exec(compile(job["code"], "<sandboxed_strategy>", "exec"), namespace)  # nosec B102
        run_backtest = namespace.get("run_backtest")
        if run_backtest is None:
            raise ValueError("strategy code did not define run_backtest(data, config)")
        portfolio = run_backtest(data, job["config"])
        if not isinstance(portfolio, dict):
            raise TypeError(f"run_backtest must return a dict, got {{type(portfolio).__name__}}")
        result["passed"] = True
        result["portfolio_summary"] = portfolio
    except BaseException as exc:  # noqa: BLE001 - must report every failure, not crash silently
        result["error"] = f"{{type(exc).__name__}}: {{exc}}"
    sys.stdout.buffer.write((json.dumps(result) + "\\n").encode("utf-8"))
    sys.stdout.buffer.flush()
"""


@dataclass
class _Worker:
    proc: subprocess.Popen[bytes]
    jobs_done: int = 0
    is_overflow: bool = False


@dataclass
class SandboxWorkerPool:
    """Not thread-safe to construct concurrently -- create exactly one via `get_pool()`."""

    size: int
    _available: list[_Worker] = field(default_factory=list, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        for _ in range(self.size):
            self._available.append(self._spawn_worker())

    def _spawn_worker(self) -> _Worker:
        total_cpu = MAX_JOBS_PER_WORKER * _CPU_SECONDS_PER_JOB_BUDGET
        script = _POOL_WORKER_SCRIPT.format(total_cpu_seconds=total_cpu)
        proc = subprocess.Popen(  # nosec B603 -- fixed argv, no shell, same posture as runner.py
            [sys.executable, "-c", script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_WORKER_ENV,
        )
        return _Worker(proc=proc)

    def _retire(self, worker: _Worker) -> None:
        # Best-effort cleanup of a worker already being killed -- if it died on its own a moment
        # earlier, that's not a real error to surface here.
        try:
            worker.proc.kill()
            worker.proc.wait(timeout=5)
        except Exception:  # noqa: BLE001 # nosec B110
            pass

    def _checkout(self) -> _Worker:
        with self._lock:
            if self._available:
                return self._available.pop()
        # Every worker is currently checked out (busy) -- spawning an extra, temporary one keeps
        # this call correct rather than deadlocking. Marked is_overflow so _checkin() retires it
        # outright afterward instead of returning it to the pool -- pool size never grows past
        # `self.size` from this path.
        worker = self._spawn_worker()
        worker.is_overflow = True
        return worker

    def _checkin(self, worker: _Worker, *, healthy: bool) -> None:
        if worker.is_overflow:
            self._retire(worker)
            return
        if not healthy or worker.jobs_done >= MAX_JOBS_PER_WORKER:
            self._retire(worker)
            worker = self._spawn_worker()
        with self._lock:
            self._available.append(worker)

    def execute(
        self,
        code: str,
        config: dict[str, Any] | None,
        data_path: Path,
        *,
        timeout: float,
    ) -> SandboxResult:
        config = config or {}
        worker = self._checkout()
        start = time.perf_counter()

        job_payload = json.dumps({"code": code, "config": config, "data_path": str(data_path)})
        job_line = (job_payload + "\n").encode("utf-8")
        try:
            if worker.proc.stdin is None:
                raise OSError("sandbox pool worker has no stdin pipe")
            worker.proc.stdin.write(job_line)
            worker.proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            self._checkin(worker, healthy=False)
            return SandboxResult(
                passed=False,
                portfolio_summary=None,
                error="sandbox pool worker died before accepting the job",
                duration_seconds=time.perf_counter() - start,
            )

        response = self._read_line_with_deadline(worker.proc, timeout + 2.0)
        duration = time.perf_counter() - start

        if response is None:
            # Timed out, or the worker died mid-job -- never trust or reuse this worker again.
            self._checkin(worker, healthy=False)
            return SandboxResult(
                passed=False,
                portfolio_summary=None,
                error=f"sandbox pool worker exceeded {timeout}s wall-clock timeout or died",
                duration_seconds=duration,
            )

        worker.jobs_done += 1
        self._checkin(worker, healthy=True)

        try:
            parsed = json.loads(response)
        except json.JSONDecodeError:
            return SandboxResult(
                passed=False,
                portfolio_summary=None,
                error=f"sandbox pool worker produced non-JSON output: {response[-500:]!r}",
                duration_seconds=duration,
            )

        return SandboxResult(
            passed=parsed["passed"],
            portfolio_summary=parsed["portfolio_summary"],
            error=parsed["error"],
            duration_seconds=duration,
        )

    @staticmethod
    def _read_line_with_deadline(
        proc: subprocess.Popen[bytes], deadline_seconds: float
    ) -> str | None:
        """Reads one newline-terminated line from `proc.stdout` without ever blocking past
        `deadline_seconds` total, even if the worker writes a large response across multiple
        underlying OS writes (a plain `readline()` after a single `select()` "ready" check can
        still block indefinitely on a partial write -- this loops, re-selecting on the remaining
        budget each time, until either a full line has arrived or the deadline is exhausted)."""
        if proc.stdout is None:
            return None
        fd = proc.stdout.fileno()
        os.set_blocking(fd, False)
        sel = selectors.DefaultSelector()
        sel.register(fd, selectors.EVENT_READ)
        deadline = time.monotonic() + deadline_seconds
        buf = b""
        try:
            while b"\n" not in buf:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                if not sel.select(timeout=remaining):
                    return None
                try:
                    chunk = os.read(fd, 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    return None  # EOF -- the worker process has died
                buf += chunk
            line, _, _ = buf.partition(b"\n")
            return line.decode("utf-8")
        finally:
            sel.close()
            os.set_blocking(fd, True)

    def shutdown(self) -> None:
        with self._lock:
            workers, self._available = self._available, []
        for worker in workers:
            self._retire(worker)


_pool_lock = threading.Lock()
_pool: SandboxWorkerPool | None = None


def get_pool(settings: Settings | None = None) -> SandboxWorkerPool:
    """Lazy singleton, same pattern as src/core/db.py's own `get_engine()` -- created on first
    real use, not at import time or app startup, so a pool that's never needed (e.g. a test run
    that never calls a real backtest) never pays its own warm-up cost."""
    global _pool
    settings = settings or get_settings()
    with _pool_lock:
        if _pool is None:
            _pool = SandboxWorkerPool(size=settings.sandbox_pool_size)
        return _pool


def execute_in_pool(
    code: str,
    config: dict[str, Any] | None = None,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    data_path: Path,
    settings: Settings | None = None,
) -> SandboxResult:
    """Uses the warm pool if enabled; falls back to the original one-shot `execute_in_sandbox()`
    if the pool is disabled or its own startup/execution raises -- a pool failure degrades to
    "slow but correct," never to "broken." Unlike `execute_in_sandbox()`, `data_path` is required
    here: the pool exists specifically for real backtests (`backtest_runner.py`), which always
    have one; there's no dummy-dataset validation use case for a pooled call."""
    settings = settings or get_settings()
    if not settings.sandbox_pool_enabled:
        return execute_in_sandbox(code, config, timeout=timeout, data_path=data_path)
    try:
        pool = get_pool(settings)
        return pool.execute(code, config, data_path, timeout=timeout)
    except Exception:  # noqa: BLE001 - any pool-level failure falls back, never propagates
        return execute_in_sandbox(code, config, timeout=timeout, data_path=data_path)
