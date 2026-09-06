"""Seeds real AgentRun rows for frontend/cypress/e2e/agent_analytics.cy.ts (REL-068's Analytics
tab, GET /agents/analytics/summary + GET /agents/analytics/trend).

That spec's own comment says plainly it was written against "real seeded AgentRun data already
confirmed non-empty in this dev DB" -- true on this long-lived dev host (years of real agent
activity), but a fresh CI Postgres starts with zero AgentRun rows at all. Both analytics endpoints
only ever look at real rows within the last `days` window (default 30) -- with none there, the
frontend renders its own honest empty state instead of a `<table>`, which is exactly the real,
reproduced CI failure ("Expected to find element: table, but never found it").

Real, not fabricated data shape: each row uses `src.agents.control.KNOWN_AGENTS`'s own real agent
names (the same graph-node identifiers `src/agents/graph.py` sets on every real AgentRun.agent_name
today) and a real Completed/Failed status mix with real start/end timestamps, so the summary's own
success-rate math and the trend chart's own day-bucketing both compute over genuine data, not one
degenerate row. `graph_thread_id` is prefixed distinctively so a re-run finds and reuses these
rather than accumulating duplicates on every CI run.

Run via `docker compose exec -T app python scripts/seed_agent_analytics_fixtures.py` (cypress-e2e
CI step) or `docker compose run --rm app python scripts/seed_agent_analytics_fixtures.py` locally.
"""

import uuid
from datetime import UTC, datetime, timedelta

from src.core.db import get_session
from src.models.agent import AgentRun

_THREAD_PREFIX = "cypress-analytics-fixture-"

# (agent_name, status, days_ago, duration_seconds) -- a real mix across the 3 agent names the
# spec's own `td` assertion names explicitly (compliance/python_code_generator/strategy_generator),
# spread over several distinct days so the trend chart has more than one real data point.
_FIXTURE_RUNS: list[tuple[str, str, int, int]] = [
    ("strategy_generator", "Completed", 1, 42),
    ("strategy_generator", "Completed", 2, 38),
    ("strategy_generator", "Failed", 3, 15),
    ("python_code_generator", "Completed", 1, 21),
    ("python_code_generator", "Completed", 2, 19),
    ("python_code_generator", "Completed", 4, 24),
    ("compliance", "Completed", 1, 6),
    ("compliance", "Completed", 2, 5),
    ("compliance", "Failed", 5, 4),
]


def _already_seeded() -> bool:
    with get_session() as session:
        return (
            session.query(AgentRun)
            .filter(AgentRun.graph_thread_id.like(f"{_THREAD_PREFIX}%"))
            .first()
            is not None
        )


def _seed() -> None:
    with get_session() as session:
        for agent_name, status, days_ago, duration_seconds in _FIXTURE_RUNS:
            started_at = datetime.now(UTC) - timedelta(days=days_ago, hours=1)
            session.add(
                AgentRun(
                    id=uuid.uuid4(),
                    graph_thread_id=f"{_THREAD_PREFIX}{uuid.uuid4()}",
                    agent_name=agent_name,
                    status=status,
                    started_at=started_at,
                    ended_at=started_at + timedelta(seconds=duration_seconds),
                )
            )
        session.commit()


def main() -> None:
    if _already_seeded():
        print("Agent analytics fixture runs already exist, reusing as-is.")
        return
    _seed()
    print(f"Seeded {len(_FIXTURE_RUNS)} real AgentRun fixture rows for the Analytics tab.")


if __name__ == "__main__":
    main()
