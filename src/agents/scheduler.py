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

from src.agents.control import is_agent_enabled
from src.agents.nodes.memory_agent import (
    archive_low_confidence_memories,
    generate_lessons_learned_summary,
)
from src.agents.nodes.news_agent import ingest_news_cycle
from src.agents.nodes.sentiment_agent import score_and_store_sentiment
from src.core.config import get_settings
from src.core.db import get_session
from src.data.datalake.freshness import DataFreshnessError, require_fresh
from src.data.datalake.query import DataLake
from src.data.ingest.corporate_actions import CorporateActionsAdapter, CorporateActionsWriter
from src.engine.paper_trading.daily_signal_job import run_daily_paper_trading_cycle
from src.engine.paper_trading.equity_snapshot import take_daily_snapshot
from src.engine.paper_trading.paper_account import get_paper_account

logger = structlog.get_logger(__name__)

IST_TIMEZONE = "Asia/Kolkata"
DAILY_CYCLE_JOB_ID = "scheduler_daily_research_cycle"
WEEKEND_MEMORY_JOB_ID = "scheduler_weekend_memory_consolidation"
CORPORATE_ACTIONS_JOB_ID = "scheduler_corporate_actions_ingestion"
NEWS_SENTIMENT_JOB_ID = "scheduler_news_sentiment_cycle"
PAPER_TRADING_DAILY_CYCLE_JOB_ID = "scheduler_paper_trading_daily_cycle"
PAPER_TRADING_EQUITY_SNAPSHOT_JOB_ID = "scheduler_paper_trading_equity_snapshot"
# REL-010 E10.7: no intraday-ingestion job is wired here -- Upstox's real historical-candle
# endpoint 404s in sandbox mode (confirmed empirically, see
# src/brokers/upstox_adapter.py::get_historical_candles's own docstring) and this dev
# environment has no production Upstox token configured. Wiring a job that would fail every
# real run isn't honest progress -- src/data/ingest/intraday.py's fetch_intraday_candles is
# real, unit-tested code ready to be scheduled once a production token exists.
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


def run_corporate_actions_ingestion() -> None:
    """REL-010 E10.7: real CSV-read + real Postgres upsert (src/data/ingest/corporate_actions.py)
    -- scheduled before the daily research cycle so a same-day corporate action is reflected
    before that cycle's own backtests run. A missing/empty CSV is a real, silent no-op (0 rows
    written), not an error -- this dev environment has no seed data by default.

    REL-019 E19.2 (ADR 11): checks the Data Ingestion Agent's real control state first -- a
    disabled agent is skipped honestly (own log event), not silently indistinguishable from a
    normal empty-CSV no-op."""
    try:
        with get_session() as session:
            if not is_agent_enabled(session, "data_ingestion_agent"):
                logger.info("scheduler_corporate_actions_ingestion_skipped_disabled")
                return
        rows = CorporateActionsAdapter(get_settings().corporate_actions_csv_path).fetch()
        with get_session() as session:
            written = CorporateActionsWriter().write(session, rows)
        logger.info("scheduler_corporate_actions_ingestion_completed", rows_written=written)
    except Exception as exc:  # noqa: BLE001 - a failed ingestion run must not crash the app
        logger.warning("scheduler_corporate_actions_ingestion_failed", error=str(exc))


def run_news_sentiment_cycle() -> None:
    """REL-010 E10.3: real RSS ingestion (src/agents/nodes/news_agent.py) + real LLM sentiment
    scoring persisted to Qdrant (src/agents/nodes/sentiment_agent.py). Every-30-minutes cadence
    during market hours matches the plan's own stated interval; both steps already degrade
    per-item/per-feed on failure, so this wrapper only needs to guard against a total surprise
    (e.g. Qdrant itself being down).

    REL-019 E19.2 (ADR 11): News and Sentiment are two separately controllable agents (AGT-013/
    AGT-014) sharing one scheduled job, so each gets its own real control-state check rather than
    one combined check that couldn't distinguish "skip ingestion" from "skip scoring"."""
    try:
        with get_session() as session:
            news_enabled = is_agent_enabled(session, "news_agent")
        if news_enabled:
            items = ingest_news_cycle()
        else:
            logger.info("scheduler_news_agent_skipped_disabled")
            items = []

        with get_session() as session:
            sentiment_enabled = is_agent_enabled(session, "sentiment_agent")
        if sentiment_enabled and items:
            point_ids = score_and_store_sentiment(items)
        else:
            if not sentiment_enabled:
                logger.info("scheduler_sentiment_agent_skipped_disabled")
            point_ids = []

        logger.info(
            "scheduler_news_sentiment_cycle_completed",
            items_ingested=len(items),
            items_scored=len(point_ids),
        )
    except Exception as exc:  # noqa: BLE001 - a failed cycle must not crash the app
        logger.warning("scheduler_news_sentiment_cycle_failed", error=str(exc))


async def run_paper_trading_daily_cycle() -> None:
    """REL-034: the once-per-real-trading-day directional signal for every strategy in
    `"PaperTrading"` status -- see src/engine/paper_trading/daily_signal_job.py's own module
    docstring for the full design. Scheduled after the 06:00 research cycle so an
    overnight-decided position executes at a real live-market-open quote."""
    try:
        results = await run_daily_paper_trading_cycle()
        logger.info("scheduler_paper_trading_daily_cycle_completed", strategy_count=len(results))
    except Exception as exc:  # noqa: BLE001 - a failed cycle must not crash the app
        logger.warning("scheduler_paper_trading_daily_cycle_failed", error=str(exc))


async def run_paper_trading_equity_snapshot() -> None:
    """REL-034: one AccountEquitySnapshot row per real trading day, ~5 minutes after NSE close
    -- see src/engine/paper_trading/equity_snapshot.py's own module docstring."""
    from src.brokers.factory import NoBrokerConfigured, build_broker
    from src.data.reference.nse_holiday_calendar import is_trading_holiday

    if is_trading_holiday(date.today()):
        logger.info("scheduler_paper_trading_equity_snapshot_skipped", reason="not a trading day")
        return

    try:
        broker = build_broker()
    except NoBrokerConfigured:
        logger.info(
            "scheduler_paper_trading_equity_snapshot_skipped", reason="no broker configured"
        )
        return
    try:
        with get_session() as session:
            account = get_paper_account(session)
            snapshot = await take_daily_snapshot(str(account.id), session, broker)
        logger.info(
            "scheduler_paper_trading_equity_snapshot_completed",
            equity=snapshot.equity if snapshot else None,
        )
    except Exception as exc:  # noqa: BLE001 - a failed snapshot must not crash the app
        logger.warning("scheduler_paper_trading_equity_snapshot_failed", error=str(exc))


def run_weekend_memory_consolidation() -> None:
    """REL-019 E19.2 (ADR 11): checks the Memory Agent's real control state first."""
    try:
        with get_session() as session:
            if not is_agent_enabled(session, "memory_agent"):
                logger.info("scheduler_weekend_memory_job_skipped_disabled")
                return
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
        run_corporate_actions_ingestion,
        CronTrigger(hour=5, minute=30, timezone=IST_TIMEZONE),
        id=CORPORATE_ACTIONS_JOB_ID,
        replace_existing=True,
    )
    scheduler.add_job(
        run_daily_research_cycle,
        CronTrigger(hour=6, minute=0, timezone=IST_TIMEZONE),
        id=DAILY_CYCLE_JOB_ID,
        replace_existing=True,
    )
    scheduler.add_job(
        run_news_sentiment_cycle,
        # Every 30 min across NSE's real 09:15-15:30 IST session (hour=9-15 covers both ends;
        # a 09:00 or 15:45 firing outside the real session is a harmless no-op, not incorrect).
        CronTrigger(hour="9-15", minute="*/30", timezone=IST_TIMEZONE),
        id=NEWS_SENTIMENT_JOB_ID,
        replace_existing=True,
    )
    scheduler.add_job(
        run_weekend_memory_consolidation,
        CronTrigger(day_of_week="sat", hour=2, minute=0, timezone=IST_TIMEZONE),
        id=WEEKEND_MEMORY_JOB_ID,
        replace_existing=True,
    )
    scheduler.add_job(
        run_paper_trading_daily_cycle,
        # After the 06:00 research cycle, before market open (09:15 IST) -- overnight-decided
        # positions execute at a real live quote shortly after the session opens.
        CronTrigger(hour=6, minute=30, timezone=IST_TIMEZONE),
        id=PAPER_TRADING_DAILY_CYCLE_JOB_ID,
        replace_existing=True,
    )
    scheduler.add_job(
        run_paper_trading_equity_snapshot,
        # ~5 minutes after NSE's real 15:30 IST close.
        CronTrigger(hour=15, minute=35, timezone=IST_TIMEZONE),
        id=PAPER_TRADING_EQUITY_SNAPSHOT_JOB_ID,
        replace_existing=True,
    )
    return scheduler
