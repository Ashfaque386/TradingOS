"""Pure aggregation over the Shadow Mode ledger (Phase 4 Epic E4.4) -- no DB session, no
Pydantic, so src/api/routers/shadow_mode.py's /status endpoint and
src/engine/go_live_gate.py's Go-Live Readiness Gate (Phase_14_Master_Development_Roadmap.md
§5.4) compute "consecutive clean days" the exact same way rather than risking two
implementations silently drifting apart.
"""

from collections import defaultdict
from dataclasses import dataclass

from src.models.shadow_mode import ShadowModeAttempt


@dataclass(frozen=True)
class DailyCleanliness:
    date: str
    attempts: int
    errors: int
    clean: bool  # at least one attempt, zero errors


def compute_daily_summary(rows: list[ShadowModeAttempt]) -> list[DailyCleanliness]:
    by_day: dict[str, list[ShadowModeAttempt]] = defaultdict(list)
    for row in rows:
        by_day[row.attempted_at.date().isoformat()].append(row)

    return [
        DailyCleanliness(
            date=day,
            attempts=len(day_rows),
            errors=sum(1 for r in day_rows if r.outcome == "Error"),
            clean=all(r.outcome == "Validated" for r in day_rows),
        )
        for day, day_rows in sorted(by_day.items())
    ]


def consecutive_clean_days(daily_summary: list[DailyCleanliness]) -> int:
    consecutive = 0
    for day in reversed(daily_summary):
        if day.clean:
            consecutive += 1
        else:
            break
    return consecutive
