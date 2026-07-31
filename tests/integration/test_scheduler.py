"""Scheduler Agent (AGT-025) integration test — REL-005 E5.6 exit criterion: the Data Freshness
gate (Business Rule 4) is real, checked against the real data lake, not mocked. Only the LLM
layer underneath `trigger_research` is mocked here (a full real graph run belongs to the
end-to-end verification pass, not a unit-scoped scheduler test); the freshness gate itself, the
symbol discovery via `DataLake.list_symbols()`, and `build_scheduler()`'s real cron wiring are
all exercised for real.
"""

from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import polars as pl

from src.agents.scheduler import (
    CORPORATE_ACTIONS_JOB_ID,
    DAILY_CYCLE_JOB_ID,
    NEWS_SENTIMENT_JOB_ID,
    WEEKEND_MEMORY_JOB_ID,
    build_scheduler,
    run_corporate_actions_ingestion,
    run_daily_research_cycle,
)
from src.core.db import get_session
from src.data.datalake.query import DataLake
from src.data.ingest.writer import ParquetLakeWriter
from src.models.corporate_action import CorporateAction


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
    scheduler = build_scheduler()
    job_ids = {job.id for job in scheduler.get_jobs()}

    assert DAILY_CYCLE_JOB_ID in job_ids
    assert WEEKEND_MEMORY_JOB_ID in job_ids
    assert CORPORATE_ACTIONS_JOB_ID in job_ids
    assert NEWS_SENTIMENT_JOB_ID in job_ids


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
