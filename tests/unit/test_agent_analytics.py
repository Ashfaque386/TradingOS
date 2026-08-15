"""REL-068: src.agents.analytics's own real aggregation math (success rate, duration
percentiles, daily bucketing), against fixture data -- the real DB-backed coverage lives in
tests/integration/test_agents_router_api.py (GET /agents/analytics/summary and .../trend)."""

from datetime import UTC, date, datetime

from src.agents.analytics import bucket_by_day, group_by_agent, summarize_runs


def _dt(day: int, hour: int = 0) -> datetime:
    return datetime(2026, 8, day, hour, tzinfo=UTC)


def test_summarize_runs_success_rate_excludes_running():
    entries = [
        ("Completed", _dt(1), _dt(1, 1)),
        ("Completed", _dt(2), _dt(2, 1)),
        ("Failed", _dt(3), _dt(3, 1)),
        ("Running", _dt(4), None),
    ]
    stats = summarize_runs(entries)
    assert stats.total_runs == 4
    assert stats.completed == 2
    assert stats.failed == 1
    assert stats.running == 1
    # 2 completed / (2 completed + 1 failed) = 2/3, not diluted by the 1 still-Running row.
    assert stats.success_rate == 2 / 3


def test_summarize_runs_success_rate_is_none_with_no_finished_runs():
    stats = summarize_runs([("Running", _dt(1), None)])
    assert stats.success_rate is None


def test_summarize_runs_duration_percentiles_only_over_completed_with_real_ended_at():
    start = _dt(1)
    entries = [
        ("Completed", start, start.replace(minute=1)),  # 60s
        ("Completed", start, start.replace(minute=2)),  # 120s
        ("Failed", start, start.replace(minute=5)),  # excluded -- not Completed
        ("Running", start, None),  # excluded -- no real ended_at
    ]
    stats = summarize_runs(entries)
    assert stats.avg_duration_seconds == 90.0
    assert stats.p50_duration_seconds == 90.0


def test_summarize_runs_durations_none_when_no_completed_run_has_ended_at():
    stats = summarize_runs([("Failed", _dt(1), _dt(1, 1))])
    assert stats.avg_duration_seconds is None
    assert stats.p50_duration_seconds is None
    assert stats.p95_duration_seconds is None


def test_group_by_agent_splits_rows_by_real_agent_name():
    rows = [
        ("ceo_agent", "Completed", _dt(1), _dt(1, 1)),
        ("compliance", "Failed", _dt(2), _dt(2, 1)),
        ("ceo_agent", "Completed", _dt(3), _dt(3, 1)),
    ]
    grouped = group_by_agent(rows)
    assert set(grouped) == {"ceo_agent", "compliance"}
    assert len(grouped["ceo_agent"]) == 2
    assert len(grouped["compliance"]) == 1


def test_bucket_by_day_only_returns_real_days_with_at_least_one_run():
    rows = [
        ("Completed", _dt(1)),
        ("Failed", _dt(1, 12)),
        ("Completed", _dt(3)),
    ]
    buckets = bucket_by_day(rows)
    # Day 2 has zero real runs -- honestly absent, not a fabricated zero-filled entry.
    assert [b.date for b in buckets] == [date(2026, 8, 1), date(2026, 8, 3)]
    assert buckets[0].total_runs == 2
    assert buckets[0].completed == 1
    assert buckets[0].failed == 1
    assert buckets[1].total_runs == 1
    assert buckets[1].completed == 1
