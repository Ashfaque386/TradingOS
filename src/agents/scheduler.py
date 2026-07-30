"""Scheduler Agent (AGT-025) — REL-005 Epic E5.6.

Real recurring trigger for the daily research cycle (SRS Workflow 1 step 1) and the Memory
Agent's weekend consolidation job (WF-06) -- both previously only reachable via a manual API
call or a manual script/test invocation; `archive_low_confidence_memories`/
`generate_lessons_learned_summary` (src/agents/nodes/memory_agent.py) are real and tested but,
before this module, had zero production call sites. Wired to the FastAPI app's own lifecycle
(src/api/main.py) via APScheduler, not a Temporal Schedule -- see pyproject.toml's dependency
comment for why (the `temporal` compose service's in-memory persistence would lose a Temporal
Schedule on every container restart).

"6:00 AM IST" is used here (SRS Workflow 1 step 1, echoed by the Scheduler/News/Data-Ingestion
Agent specs in Phase_4_AI_Agent_Design.md) even though the CEO Agent's own §1 entry and the
roadmap checklist say "7:00 AM IST" -- a genuine inconsistency across the design docs, found
during REL-005 implementation. SRS Workflow 1 is treated as the more authoritative single source
since it's echoed by 3 other agent specs, not 1.
"""

from datetime import date

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.agents.nodes.memory_agent import (
    archive_low_confidence_memories,
    generate_lessons_learned_summary,
)
from src.core.config import get_settings
from src.data.datalake.freshness import DataFreshnessError, require_fresh
from src.data.datalake.query import DataLake

logger = structlog.get_logger(__name__)

IST_TIMEZONE = "Asia/Kolkata"
DAILY_CYCLE_JOB_ID = "scheduler_daily_research_cycle"
WEEKEND_MEMORY_JOB_ID = "scheduler_weekend_memory_consolidation"
# REL-008's weekly-retrain/drift-check jobs (WEEKLY_MODEL_RETRAIN_JOB_ID/DRIFT_CHECK_JOB_ID) were
# removed 2026-07-30: the whole ML/RL platform (Phase 5) was disabled pending a host resource
# upgrade -- see Phase_5_Machine_Learning_Architecture.md's own status banner and
# Phase_14_Master_Development_Roadmap.md's REL-008 section for why. Re-add both jobs (and
# run_weekly_model_retrain/run_drift_check below) when Phase 5 is re-implemented.


def run_daily_research_cycle() -> None:
    """Business Rule 4 (Data Freshness) gate, then the real research-cycle trigger -- deferring
    rather than triggering a cycle against a stale or empty data lake, per the Scheduler Agent
    spec's "retry or defer triggers on upstream failure rather than launching a pipeline against
    stale or incomplete data." Deferred import of `trigger_research` avoids a circular import
    (src.api.main -> this module -> src.api.routers.agents, which itself is imported by
    src.api.main when building the FastAPI app)."""
    from src.api.routers.agents import trigger_research

    lake = DataLake(get_settings().data_lake_root / "ohlcv_daily")
    symbols = lake.list_symbols()
    if not symbols:
        logger.warning("scheduler_daily_cycle_skipped", reason="no symbols ingested")
        return
    try:
        require_fresh(lake, symbols, as_of=date.today())
    except DataFreshnessError as exc:
        logger.warning("scheduler_daily_cycle_deferred", error=str(exc))
        return

    trigger_research()
    logger.info("scheduler_daily_cycle_triggered", symbols=symbols)


def run_weekend_memory_consolidation() -> None:
    try:
        archived = archive_low_confidence_memories()
        summary = generate_lessons_learned_summary()
        logger.info(
            "scheduler_weekend_memory_job_completed",
            archived_count=len(archived),
            summary_length=len(summary),
        )
    except Exception as exc:  # noqa: BLE001 - a failed consolidation run must not crash the app
        logger.warning("scheduler_weekend_memory_job_failed", error=str(exc))


def build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=IST_TIMEZONE)
    scheduler.add_job(
        run_daily_research_cycle,
        CronTrigger(hour=6, minute=0, timezone=IST_TIMEZONE),
        id=DAILY_CYCLE_JOB_ID,
        replace_existing=True,
    )
    scheduler.add_job(
        run_weekend_memory_consolidation,
        CronTrigger(day_of_week="sat", hour=2, minute=0, timezone=IST_TIMEZONE),
        id=WEEKEND_MEMORY_JOB_ID,
        replace_existing=True,
    )
    return scheduler
