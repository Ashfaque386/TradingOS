"""Scheduler Agent (AGT-025) integration test — REL-005 E5.6 exit criterion: the Data Freshness
gate (Business Rule 4) is real, checked against the real data lake, not mocked. Only the LLM
layer underneath `trigger_research` is mocked here (a full real graph run belongs to the
end-to-end verification pass, not a unit-scoped scheduler test); the freshness gate itself, the
symbol discovery via `DataLake.list_symbols()`, and `build_scheduler()`'s real cron wiring are
all exercised for real.
"""

from datetime import date, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import polars as pl
import pytest

from src.agents.scheduler import (
    AUDIT_ARCHIVE_JOB_ID,
    AUDIT_CHAIN_VERIFICATION_JOB_ID,
    CORPORATE_ACTIONS_JOB_ID,
    DAILY_CYCLE_JOB_ID,
    DATA_LAKE_BACKUP_JOB_ID,
    JOB_REGISTRY,
    MARKET_DATA_INGESTION_JOB_ID,
    NEWS_SENTIMENT_JOB_ID,
    PAPER_TRADING_DAILY_CYCLE_JOB_ID,
    PAPER_TRADING_EQUITY_SNAPSHOT_JOB_ID,
    SHADOW_MODE_DAILY_CYCLE_JOB_ID,
    WEEKEND_MEMORY_JOB_ID,
    build_scheduler,
    run_audit_archive_job,
    run_audit_chain_verification_job,
    run_corporate_actions_ingestion,
    run_daily_research_cycle,
    run_data_lake_backup_job,
    run_shadow_mode_daily_cycle,
)
from src.core.db import get_session
from src.data.datalake.query import DataLake
from src.data.ingest.writer import ParquetLakeWriter
from src.models.corporate_action import CorporateAction


@pytest.fixture(autouse=True)
def _reset_live_scheduler_global():
    """REL-081: `build_scheduler()` now always sets the module-level `_scheduler_instance`
    global (even when never `.start()`-ed, as every test below does) -- reset around every test
    in this file so it never leaks into another test/file's `get_running_scheduler()` call."""
    import src.agents.scheduler as scheduler_module

    scheduler_module._scheduler_instance = None
    yield
    scheduler_module._scheduler_instance = None


def _seed_fresh_symbol(tmp_path, symbol: str) -> None:
    ParquetLakeWriter(tmp_path).write(
        pl.DataFrame(
            {
                "symbol": [symbol],
                "date": [date.today() - timedelta(days=1)],
                "open": [100.0],
                "high": [101.0],
                "low": [99.0],
                "close": [100.5],
                "volume": [1000],
            }
        )
    )


def _seed_stale_symbol(tmp_path, symbol: str) -> None:
    ParquetLakeWriter(tmp_path).write(
        pl.DataFrame(
            {
                "symbol": [symbol],
                "date": [date(2020, 1, 2)],
                "open": [100.0],
                "high": [101.0],
                "low": [99.0],
                "close": [100.5],
                "volume": [1000],
            }
        )
    )


def test_run_daily_research_cycle_skips_when_no_symbols_ingested(tmp_path):
    fake_settings = type("S", (), {"data_lake_root": tmp_path})()
    with (
        patch("src.agents.scheduler.get_settings", return_value=fake_settings),
        patch("src.api.routers.agents.trigger_research") as mock_trigger,
    ):
        run_daily_research_cycle()

    mock_trigger.assert_not_called()


def test_run_daily_research_cycle_defers_when_data_is_stale(tmp_path):
    _seed_stale_symbol(tmp_path / "ohlcv_daily", "RELIANCE")
    fake_settings = type("S", (), {"data_lake_root": tmp_path})()
    with (
        patch("src.agents.scheduler.get_settings", return_value=fake_settings),
        patch("src.api.routers.agents.trigger_research") as mock_trigger,
    ):
        run_daily_research_cycle()

    mock_trigger.assert_not_called()


def test_run_daily_research_cycle_triggers_when_data_is_fresh(tmp_path):
    _seed_fresh_symbol(tmp_path / "ohlcv_daily", "RELIANCE")
    fake_settings = type("S", (), {"data_lake_root": tmp_path})()
    with (
        patch("src.agents.scheduler.get_settings", return_value=fake_settings),
        patch("src.api.routers.agents.trigger_research") as mock_trigger,
    ):
        run_daily_research_cycle()

    mock_trigger.assert_called_once()


def test_data_lake_list_symbols_matches_what_freshness_gate_checks(tmp_path):
    """Sanity check that the gate really is symbol-driven, not hardcoded -- seeding two real
    symbols means both get checked, confirmed via a real DataLake instance, not a mock."""
    lake_root = tmp_path / "ohlcv_daily"
    _seed_fresh_symbol(lake_root, "RELIANCE")
    _seed_fresh_symbol(lake_root, "TCS")

    assert DataLake(lake_root).list_symbols() == ["RELIANCE", "TCS"]


def test_build_scheduler_registers_every_real_cron_job():
    """REL-081: 11 real jobs (7 pre-existing + the 4 that used to be external Windows Scheduled
    Tasks), + 1 more (DB-022's DuckDB catalog view refresh) = 12 total -- asserted against the
    live JOB_REGISTRY itself, not a hand-copied count, so this can't silently under-count the way
    the plan's own initial "10" draft did."""
    scheduler = build_scheduler()
    job_ids = {job.id for job in scheduler.get_jobs()}

    assert job_ids == set(JOB_REGISTRY.keys())
    assert len(job_ids) == 12

    assert DAILY_CYCLE_JOB_ID in job_ids
    assert WEEKEND_MEMORY_JOB_ID in job_ids
    assert CORPORATE_ACTIONS_JOB_ID in job_ids
    assert NEWS_SENTIMENT_JOB_ID in job_ids
    assert PAPER_TRADING_DAILY_CYCLE_JOB_ID in job_ids
    assert PAPER_TRADING_EQUITY_SNAPSHOT_JOB_ID in job_ids
    assert MARKET_DATA_INGESTION_JOB_ID in job_ids
    assert SHADOW_MODE_DAILY_CYCLE_JOB_ID in job_ids
    assert AUDIT_ARCHIVE_JOB_ID in job_ids
    assert AUDIT_CHAIN_VERIFICATION_JOB_ID in job_ids
    assert DATA_LAKE_BACKUP_JOB_ID in job_ids


def test_build_scheduler_pauses_a_job_disabled_via_config():
    from datetime import UTC, datetime

    from src.models.scheduled_job import ScheduledJobConfig

    with get_session() as session:
        session.query(ScheduledJobConfig).filter(
            ScheduledJobConfig.job_id == MARKET_DATA_INGESTION_JOB_ID
        ).delete()
        session.add(
            ScheduledJobConfig(
                job_id=MARKET_DATA_INGESTION_JOB_ID,
                cron_expression=JOB_REGISTRY[MARKET_DATA_INGESTION_JOB_ID].default_cron,
                enabled=False,
                updated_at=datetime.now(UTC),
            )
        )
        session.commit()

    try:
        scheduler = build_scheduler()
        job = scheduler.get_job(MARKET_DATA_INGESTION_JOB_ID)
        assert job is not None
        assert job.next_run_time is None  # paused -- nothing scheduled to fire
    finally:
        with get_session() as session:
            session.query(ScheduledJobConfig).filter(
                ScheduledJobConfig.job_id == MARKET_DATA_INGESTION_JOB_ID
            ).delete()
            session.commit()


# --- REL-081: the 4 jobs previously driven by external Windows Scheduled Tasks -----------------


def test_run_shadow_mode_daily_cycle_attempts_every_configured_broker():
    fake_row = type("Row", (), {"outcome": "Validated", "used_real_sandbox": True})()
    with (
        patch(
            "src.api.routers.shadow_mode.resolve_daily_shadow_mode_symbols",
            new_callable=AsyncMock,
            return_value={"zerodha": "INFY", "upstox": None},
        ),
        patch(
            "src.api.routers.shadow_mode.run_one_shadow_mode_attempt",
            new_callable=AsyncMock,
            return_value=fake_row,
        ) as mock_attempt,
    ):
        import asyncio

        result = asyncio.run(run_shadow_mode_daily_cycle())

    assert result.status == "Completed"
    assert "zerodha" in result.summary
    assert "upstox: not configured" in result.summary
    mock_attempt.assert_awaited_once()


def test_run_audit_archive_job_reports_completed_on_zero_pending_rows():
    with patch("src.core.audit_archive.archive_pending_rows", return_value=(0, 0)):
        result = run_audit_archive_job()
    assert result.status == "Completed"
    assert "0 row(s) archived" in result.summary


def test_run_audit_archive_job_reports_failed_when_any_row_fails():
    with patch("src.core.audit_archive.archive_pending_rows", return_value=(2, 1)):
        result = run_audit_archive_job()
    assert result.status == "Failed"
    assert "1 failure(s)" in result.summary


def test_run_audit_chain_verification_job_completes_on_no_divergence():
    fake_live = type("Live", (), {"valid": True, "rows_checked": 5, "first_broken_id": None})()
    fake_report = type(
        "Report",
        (),
        {
            "ok": True,
            "live": fake_live,
            "archived_rows_checked": 3,
            "archive_valid": True,
            "archive_broken_ids": [],
            "diverged_ids": [],
        },
    )()
    with patch("src.core.audit_chain_monitor.run_divergence_check", return_value=fake_report):
        import asyncio

        result = asyncio.run(run_audit_chain_verification_job())
    assert result.status == "Completed"


def test_run_audit_chain_verification_job_alerts_and_fails_on_divergence():
    fake_live = type("Live", (), {"valid": False, "rows_checked": 5, "first_broken_id": 42})()
    fake_report = type(
        "Report",
        (),
        {
            "ok": False,
            "live": fake_live,
            "archived_rows_checked": 3,
            "archive_valid": True,
            "archive_broken_ids": [],
            "diverged_ids": [],
        },
    )()
    with (
        patch("src.core.audit_chain_monitor.run_divergence_check", return_value=fake_report),
        patch(
            "src.core.ops_alerts.send_ops_alert", new_callable=AsyncMock, return_value=[]
        ) as mock_alert,
    ):
        import asyncio

        result = asyncio.run(run_audit_chain_verification_job())
    assert result.status == "Failed"
    mock_alert.assert_awaited_once()


def test_run_data_lake_backup_job_completed_when_no_failures():
    fake_result = type(
        "R",
        (),
        {"files_backed_up": 3, "files_found": 3, "backup_root": Path("/tmp/x"), "failures": []},
    )()
    with patch("src.data.datalake.backup.run_backup_cycle", return_value=fake_result):
        result = run_data_lake_backup_job()
    assert result.status == "Completed"
    assert "3/3" in result.summary


def test_run_data_lake_backup_job_failed_on_an_empty_lake():
    fake_result = type(
        "R",
        (),
        {
            "files_backed_up": 0,
            "files_found": 0,
            "backup_root": Path("/tmp/x"),
            "failures": ["No Parquet files found -- nothing to back up."],
        },
    )()
    with patch("src.data.datalake.backup.run_backup_cycle", return_value=fake_result):
        result = run_data_lake_backup_job()
    assert result.status == "Failed"


def test_run_corporate_actions_ingestion_with_no_seed_file_is_a_real_silent_no_op(monkeypatch):
    """REL-010 E10.7: this dev environment has no seed CSV by default -- a real, honest no-op
    (0 rows), not an error, matching CorporateActionsAdapter.fetch()'s own documented behavior
    for a missing file."""
    from src.core.config import get_settings

    monkeypatch.setattr(
        get_settings(), "corporate_actions_csv_path", Path("/tmp/does-not-exist.csv")
    )
    run_corporate_actions_ingestion()  # must not raise


def test_run_corporate_actions_ingestion_writes_a_real_seeded_csv(tmp_path, monkeypatch):
    from src.core.config import get_settings

    symbol = "TEST-SCHEDULER-E10.7"
    csv_path = tmp_path / "corporate_actions.csv"
    csv_path.write_text(
        "symbol,ex_date,action_type,ratio_numerator,ratio_denominator,dividend_amount,source\n"
        f"{symbol},2024-05-01,BONUS,1,2,,test-source\n"
    )
    monkeypatch.setattr(get_settings(), "corporate_actions_csv_path", csv_path)

    try:
        run_corporate_actions_ingestion()
        with get_session() as session:
            row = (
                session.query(CorporateAction)
                .filter(CorporateAction.symbol == symbol)
                .one_or_none()
            )
        assert row is not None
        assert row.action_type == "BONUS"
    finally:
        with get_session() as session:
            session.query(CorporateAction).filter(CorporateAction.symbol == symbol).delete()
            session.commit()
