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

from datetime import date, timedelta
from typing import Literal, cast

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.agents.nodes.memory_agent import (
    archive_low_confidence_memories,
    generate_lessons_learned_summary,
)
from src.core.config import get_settings
from src.core.db import get_session
from src.data.datalake.freshness import DataFreshnessError, require_fresh
from src.data.datalake.query import DataLake

logger = structlog.get_logger(__name__)

IST_TIMEZONE = "Asia/Kolkata"
DAILY_CYCLE_JOB_ID = "scheduler_daily_research_cycle"
WEEKEND_MEMORY_JOB_ID = "scheduler_weekend_memory_consolidation"
# REL-008 E8.5: two distinct retrain triggers reconciling a real Phase_3/Phase_5 design-doc
# inconsistency (weekly-scheduled retrain uses "the latest week's data" per Phase_3 §7; a
# drift-triggered retrain uses "the most recent 6 months" per Phase_5 §6) -- both real triggers,
# both funnel through the same src/ml/training/orchestrator.py::run_training_job(), differing
# only in window size and trigger_reason.
WEEKLY_MODEL_RETRAIN_JOB_ID = "scheduler_weekly_model_retrain"
DRIFT_CHECK_JOB_ID = "scheduler_drift_check"


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


def run_weekly_model_retrain() -> None:
    """REL-008 E8.5 (weekly half): a cheap, small-window retrain over the last week's real data
    for every real, currently-ingested symbol -- registers a new Staging candidate per symbol,
    never promotes (promotion is always a separate, human-role-gated API call)."""
    from src.ml.training.orchestrator import run_training_job

    lake = DataLake(get_settings().data_lake_root / "ohlcv_daily")
    symbols = lake.list_symbols()
    if not symbols:
        logger.warning("scheduler_weekly_retrain_skipped", reason="no symbols ingested")
        return

    today = date.today()
    window_start = today - timedelta(days=7)
    trained, failed = [], []
    for symbol in symbols:
        try:
            with get_session() as session:
                model = run_training_job(
                    session,
                    model_type="LightGBM",
                    task="classification",
                    symbols=[symbol],
                    window_start=window_start,
                    window_end=today,
                    trigger_reason="weekly_scheduled",
                )
                session.commit()
                trained.append(str(model.id))
        except Exception as exc:  # noqa: BLE001 - one bad symbol must not abort the whole job
            logger.warning("scheduler_weekly_retrain_symbol_failed", symbol=symbol, error=str(exc))
            failed.append(symbol)

    logger.info("scheduler_weekly_retrain_completed", trained=trained, failed=failed)


def run_drift_check() -> None:
    """REL-008 E8.5 (drift half): checks every real Production model for feature drift / rolling-
    Sharpe degradation, staging a new drift-triggered retrain candidate when triggered. Never
    promotes -- see check_drift_and_recommend_retrain()'s own docstring."""
    from sqlalchemy import select

    from src.ml.drift.monitor import check_drift_and_recommend_retrain
    from src.models.ml import MLModel

    lake = DataLake(get_settings().data_lake_root / "ohlcv_daily")
    symbols = lake.list_symbols()
    triggered, checked = [], []
    try:
        with get_session() as session:
            production_types = session.scalars(
                select(MLModel.model_type).where(MLModel.stage == "Production").distinct()
            ).all()
            # Drift-triggered retraining only exists for the supervised path (run_training_job()
            # only knows how to route "LightGBM"/"TFT-PyTorch") -- RL policy types (PPO-RL/
            # SAC-RL) have no retrain path here and must be skipped, not misrouted into a
            # supervised training run.
            supervised_types: list[Literal["LightGBM", "TFT-PyTorch"]] = [
                cast(Literal["LightGBM", "TFT-PyTorch"], t)
                for t in production_types
                if t in ("LightGBM", "TFT-PyTorch")
            ]
            for model_type in supervised_types:
                for symbol in symbols:
                    result = check_drift_and_recommend_retrain(
                        session, model_type=model_type, task="classification", symbol=symbol
                    )
                    checked.append(symbol)
                    if result.triggered:
                        session.commit()
                        triggered.append(symbol)
    except Exception as exc:  # noqa: BLE001 - a drift-check failure must not crash the app
        logger.warning("scheduler_drift_check_failed", error=str(exc))
        return

    logger.info("scheduler_drift_check_completed", checked=checked, triggered=triggered)


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
    scheduler.add_job(
        run_weekly_model_retrain,
        CronTrigger(day_of_week="sun", hour=3, minute=0, timezone=IST_TIMEZONE),
        id=WEEKLY_MODEL_RETRAIN_JOB_ID,
        replace_existing=True,
    )
    scheduler.add_job(
        run_drift_check,
        CronTrigger(hour=5, minute=0, timezone=IST_TIMEZONE),
        id=DRIFT_CHECK_JOB_ID,
        replace_existing=True,
    )
    return scheduler
