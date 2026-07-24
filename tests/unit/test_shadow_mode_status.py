"""src/engine/shadow_mode_status.py unit tests (Phase 4 Epic E4.4) -- pure function, no DB.
Mirrors the aggregation src/api/routers/shadow_mode.py's /status endpoint now delegates to.
"""

from datetime import UTC, datetime, timedelta

from src.engine.shadow_mode_status import compute_daily_summary, consecutive_clean_days
from src.models.shadow_mode import ShadowModeAttempt


def _attempt(*, days_ago: int, outcome: str) -> ShadowModeAttempt:
    return ShadowModeAttempt(
        broker="zerodha",
        symbol="INFY",
        side="BUY",
        request_payload={},
        outcome=outcome,
        error_detail=None,
        latency_ms=1.0,
        used_real_sandbox=False,
        attempted_at=datetime.now(UTC) - timedelta(days=days_ago),
    )


def test_a_single_error_breaks_the_streak_at_that_day():
    rows = [
        _attempt(days_ago=2, outcome="Validated"),
        _attempt(days_ago=1, outcome="Error"),
        _attempt(days_ago=0, outcome="Validated"),
    ]

    daily = compute_daily_summary(rows)

    assert consecutive_clean_days(daily) == 1  # only "today" is clean, yesterday broke the streak


def test_all_clean_days_count_the_full_streak():
    rows = [_attempt(days_ago=d, outcome="Validated") for d in range(3, -1, -1)]

    daily = compute_daily_summary(rows)

    assert consecutive_clean_days(daily) == 4


def test_a_day_with_mixed_outcomes_is_not_clean():
    rows = [
        _attempt(days_ago=0, outcome="Validated"),
        _attempt(days_ago=0, outcome="Error"),
    ]

    daily = compute_daily_summary(rows)

    assert len(daily) == 1
    assert daily[0].clean is False
    assert consecutive_clean_days(daily) == 0


def test_no_attempts_at_all_is_honestly_zero():
    assert consecutive_clean_days(compute_daily_summary([])) == 0
