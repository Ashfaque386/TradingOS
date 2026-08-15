"""Real per-agent execution analytics over the AgentRun ledger (src/models/agent.py) --
success rate, duration percentiles, and daily run-volume, for GET /agents/analytics/summary and
GET /agents/analytics/trend (REL-068). Pure functions over already-fetched rows so the router
stays a thin SQLAlchemy-fetch-then-call wrapper and this math is independently unit-testable,
matching this codebase's own established pattern (src.data.market_pulse, src.data.features.
indicators, src.data.datalake.freshness) of keeping real business logic out of the router.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import numpy as np

RunRow = tuple[str, datetime, datetime | None]
"""(status, started_at, ended_at) -- the 3 columns GET /agents/analytics/* actually needs from
each real AgentRun row."""


@dataclass(frozen=True)
class AgentRunStats:
    total_runs: int
    completed: int
    failed: int
    running: int
    success_rate: float | None
    avg_duration_seconds: float | None
    p50_duration_seconds: float | None
    p95_duration_seconds: float | None


def summarize_runs(entries: list[RunRow]) -> AgentRunStats:
    """`success_rate` excludes in-flight `Running` rows from its denominator (completed /
    (completed + failed)) -- the honest definition, not diluted by runs that haven't finished
    yet, `None` when no run has finished either way. Duration percentiles are computed only over
    real `Completed` runs that have a real `ended_at` -- never fabricated for a still-running or
    failed row that has no real completion time."""
    completed = sum(1 for status, _, _ in entries if status == "Completed")
    failed = sum(1 for status, _, _ in entries if status == "Failed")
    running = sum(1 for status, _, _ in entries if status == "Running")
    finished = completed + failed
    success_rate = (completed / finished) if finished > 0 else None

    durations = [
        (ended_at - started_at).total_seconds()
        for status, started_at, ended_at in entries
        if status == "Completed" and ended_at is not None
    ]
    avg_duration = float(np.mean(durations)) if durations else None
    p50_duration = float(np.percentile(durations, 50)) if durations else None
    p95_duration = float(np.percentile(durations, 95)) if durations else None

    return AgentRunStats(
        total_runs=len(entries),
        completed=completed,
        failed=failed,
        running=running,
        success_rate=success_rate,
        avg_duration_seconds=avg_duration,
        p50_duration_seconds=p50_duration,
        p95_duration_seconds=p95_duration,
    )


def group_by_agent(
    rows: list[tuple[str, str, datetime, datetime | None]],
) -> dict[str, list[RunRow]]:
    """`rows` are (agent_name, status, started_at, ended_at) tuples -- the 4 columns
    GET /agents/analytics/summary fetches, grouped into one `RunRow` list per real `agent_name`."""
    by_agent: dict[str, list[RunRow]] = {}
    for agent_name, status, started_at, ended_at in rows:
        by_agent.setdefault(agent_name, []).append((status, started_at, ended_at))
    return by_agent


@dataclass(frozen=True)
class DailyRunBucket:
    date: date
    total_runs: int
    completed: int
    failed: int


def bucket_by_day(rows: list[tuple[str, datetime]]) -> list[DailyRunBucket]:
    """`rows` are (status, started_at) tuples. Only real days with at least 1 real run are
    returned, sorted ascending -- never a zero-filled synthetic day standing in for a real gap in
    the ledger."""
    by_day: dict[date, dict[str, int]] = {}
    for status, started_at in rows:
        day = started_at.date()
        bucket = by_day.setdefault(day, {"total": 0, "completed": 0, "failed": 0})
        bucket["total"] += 1
        if status == "Completed":
            bucket["completed"] += 1
        elif status == "Failed":
            bucket["failed"] += 1

    return [
        DailyRunBucket(
            date=day,
            total_runs=bucket["total"],
            completed=bucket["completed"],
            failed=bucket["failed"],
        )
        for day, bucket in sorted(by_day.items())
    ]
