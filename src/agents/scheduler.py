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

REL-081: real, in-app schedule/history/status for every job here, replacing the 4 Windows
Scheduled Tasks (Shadow Mode, Audit Archive, Audit Chain Verification, Data Lake Backup) that
previously drove those jobs externally -- confirmed unreliable this session
(`Get-ScheduledTaskInfo` showed real launch/kill failures on all 4, `LogonType=Interactive` only
firing within an active desktop session). Deliberately keeps `AsyncIOScheduler`'s default
in-memory job store rather than adopting a persistent one (e.g. `SQLAlchemyJobStore`): this
module already re-derives its entire job set from code on every process start
(`src/api/main.py`'s lifespan), so nothing needs to "survive a job definition across restarts" --
a persistent job store would only add pickling risk for closures holding live DB/broker state to
solve a problem this app doesn't have. Instead, `ScheduledJobConfig` (a real Postgres table) is
the source of truth for *schedule* only (cron expression + enabled), read once at
`build_scheduler()` time and re-applied to the *live* `AsyncIOScheduler` instance via
`reschedule_job`/`pause_job`/`resume_job` when edited through `src.api.routers.scheduled_jobs` --
mirrors `AgentControlState`'s own precedent (a config table separate from the mechanism it
configures; no row for a `job_id` means "use the hardcoded default", the same fail-open
convention `is_agent_enabled` already established).
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal, cast

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from sqlalchemy import select
from sqlalchemy.orm import Session

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
from src.data.ingest.scheduled_sync import run_incremental_ingestion
from src.data.reference.nse_holiday_calendar import is_trading_holiday
from src.engine.paper_trading.daily_signal_job import run_daily_paper_trading_cycle
from src.engine.paper_trading.equity_snapshot import take_daily_snapshot
from src.engine.paper_trading.paper_account import get_paper_account
from src.models.scheduled_job import ScheduledJobConfig, ScheduledJobRun

logger = structlog.get_logger(__name__)

IST_TIMEZONE = "Asia/Kolkata"
DAILY_CYCLE_JOB_ID = "scheduler_daily_research_cycle"
WEEKEND_MEMORY_JOB_ID = "scheduler_weekend_memory_consolidation"
CORPORATE_ACTIONS_JOB_ID = "scheduler_corporate_actions_ingestion"
NEWS_SENTIMENT_JOB_ID = "scheduler_news_sentiment_cycle"
PAPER_TRADING_DAILY_CYCLE_JOB_ID = "scheduler_paper_trading_daily_cycle"
PAPER_TRADING_EQUITY_SNAPSHOT_JOB_ID = "scheduler_paper_trading_equity_snapshot"
MARKET_DATA_INGESTION_JOB_ID = "scheduler_market_data_ingestion"
# REL-081: the 4 jobs that used to be driven by external Windows Scheduled Tasks.
SHADOW_MODE_DAILY_CYCLE_JOB_ID = "scheduler_shadow_mode_daily_cycle"
AUDIT_ARCHIVE_JOB_ID = "scheduler_audit_archive"
AUDIT_CHAIN_VERIFICATION_JOB_ID = "scheduler_audit_chain_verification"
DATA_LAKE_BACKUP_JOB_ID = "scheduler_data_lake_backup"
DUCKDB_CATALOG_REFRESH_JOB_ID = "scheduler_duckdb_catalog_refresh"
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


@dataclass(frozen=True)
class JobResult:
    """REL-081: every scheduled job function now returns one of these (instead of `None`) so
    `_tracked`/`_tracked_async` below can write a real, honest execution-history row --
    `status`/`summary` are built from the exact same variables each function already logs via
    structlog, not new information; this is what makes the history real rather than "the job
    didn't raise" being the only signal available."""

    status: Literal["Completed", "Failed", "Skipped"]
    summary: str


def run_daily_research_cycle() -> JobResult:
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
        return JobResult("Skipped", "no symbols ingested")
    try:
        require_fresh(lake, symbols, as_of=date.today())
    except DataFreshnessError as exc:
        logger.warning("scheduler_daily_cycle_deferred", error=str(exc))
        return JobResult("Skipped", f"data not fresh: {exc}")

    trigger_research()
    logger.info("scheduler_daily_cycle_triggered", symbols=symbols)
    return JobResult("Completed", f"research cycle triggered for {len(symbols)} symbol(s)")


def run_corporate_actions_ingestion() -> JobResult:
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
                return JobResult("Skipped", "data_ingestion_agent disabled")
        rows = CorporateActionsAdapter(get_settings().corporate_actions_csv_path).fetch()
        with get_session() as session:
            written = CorporateActionsWriter().write(session, rows)
        logger.info("scheduler_corporate_actions_ingestion_completed", rows_written=written)
        return JobResult("Completed", f"{written} row(s) written")
    except Exception as exc:  # noqa: BLE001 - a failed ingestion run must not crash the app
        logger.warning("scheduler_corporate_actions_ingestion_failed", error=str(exc))
        return JobResult("Failed", str(exc))


def run_market_data_ingestion() -> JobResult:
    """REL-072: real scheduled incremental ingestion (src/data/ingest/scheduled_sync.py) --
    closes the last manual-step gap Phase 1 (REL-070)/Phase 2 (REL-071) left open. Runs before
    `run_corporate_actions_ingestion`/`run_daily_research_cycle` so the lake is fresh before the
    06:00 freshness gate checks it. Skipped honestly on a real NSE non-trading day (same
    `is_trading_holiday` check `run_paper_trading_equity_snapshot` already makes) -- there's
    nothing new to fetch.

    REL-019 E19.2 (ADR 11): reuses the Data Ingestion Agent's real control state, same as
    `run_corporate_actions_ingestion` above."""
    if is_trading_holiday(date.today()):
        logger.info("scheduler_market_data_ingestion_skipped", reason="not a trading day")
        return JobResult("Skipped", "not a trading day")
    try:
        with get_session() as session:
            if not is_agent_enabled(session, "data_ingestion_agent"):
                logger.info("scheduler_market_data_ingestion_skipped_disabled")
                return JobResult("Skipped", "data_ingestion_agent disabled")
        summary = run_incremental_ingestion()
        logger.info(
            "scheduler_market_data_ingestion_completed",
            backfilled=len(summary.symbols_backfilled),
            topped_up=len(summary.symbols_topped_up),
            failed=len(summary.symbols_failed),
        )
        return JobResult(
            "Completed",
            f"backfilled={len(summary.symbols_backfilled)} "
            f"topped_up={len(summary.symbols_topped_up)} failed={len(summary.symbols_failed)}",
        )
    except Exception as exc:  # noqa: BLE001 - a failed ingestion run must not crash the app
        logger.warning("scheduler_market_data_ingestion_failed", error=str(exc))
        return JobResult("Failed", str(exc))


def run_news_sentiment_cycle() -> JobResult:
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
        return JobResult("Completed", f"items_ingested={len(items)} items_scored={len(point_ids)}")
    except Exception as exc:  # noqa: BLE001 - a failed cycle must not crash the app
        logger.warning("scheduler_news_sentiment_cycle_failed", error=str(exc))
        return JobResult("Failed", str(exc))


async def run_paper_trading_daily_cycle() -> JobResult:
    """REL-034: the once-per-real-trading-day directional signal for every strategy in
    `"PaperTrading"` status -- see src/engine/paper_trading/daily_signal_job.py's own module
    docstring for the full design. Scheduled after the 06:00 research cycle so an
    overnight-decided position executes at a real live-market-open quote."""
    try:
        results = await run_daily_paper_trading_cycle()
        logger.info("scheduler_paper_trading_daily_cycle_completed", strategy_count=len(results))
        return JobResult("Completed", f"strategy_count={len(results)}")
    except Exception as exc:  # noqa: BLE001 - a failed cycle must not crash the app
        logger.warning("scheduler_paper_trading_daily_cycle_failed", error=str(exc))
        return JobResult("Failed", str(exc))


async def run_paper_trading_equity_snapshot() -> JobResult:
    """REL-034: one AccountEquitySnapshot row per real trading day, ~5 minutes after NSE close
    -- see src/engine/paper_trading/equity_snapshot.py's own module docstring."""
    from src.brokers.factory import NoBrokerConfigured, build_broker

    if is_trading_holiday(date.today()):
        logger.info("scheduler_paper_trading_equity_snapshot_skipped", reason="not a trading day")
        return JobResult("Skipped", "not a trading day")

    try:
        broker = build_broker()
    except NoBrokerConfigured:
        logger.info(
            "scheduler_paper_trading_equity_snapshot_skipped", reason="no broker configured"
        )
        return JobResult("Skipped", "no broker configured")
    try:
        with get_session() as session:
            account = get_paper_account(session)
            snapshot = await take_daily_snapshot(str(account.id), session, broker)
        logger.info(
            "scheduler_paper_trading_equity_snapshot_completed",
            equity=snapshot.equity if snapshot else None,
        )
        return JobResult("Completed", f"equity={snapshot.equity if snapshot else None}")
    except Exception as exc:  # noqa: BLE001 - a failed snapshot must not crash the app
        logger.warning("scheduler_paper_trading_equity_snapshot_failed", error=str(exc))
        return JobResult("Failed", str(exc))


def run_weekend_memory_consolidation() -> JobResult:
    """REL-019 E19.2 (ADR 11): checks the Memory Agent's real control state first."""
    try:
        with get_session() as session:
            if not is_agent_enabled(session, "memory_agent"):
                logger.info("scheduler_weekend_memory_job_skipped_disabled")
                return JobResult("Skipped", "memory_agent disabled")
        archived = archive_low_confidence_memories()
        summary = generate_lessons_learned_summary()
        logger.info(
            "scheduler_weekend_memory_job_completed",
            archived_count=len(archived),
            summary_length=len(summary),
        )
        return JobResult(
            "Completed", f"archived_count={len(archived)} summary_length={len(summary)}"
        )
    except Exception as exc:  # noqa: BLE001 - a failed consolidation run must not crash the app
        logger.warning("scheduler_weekend_memory_job_failed", error=str(exc))
        return JobResult("Failed", str(exc))


# --- REL-081: the 4 jobs previously driven by external Windows Scheduled Tasks -----------------


async def run_shadow_mode_daily_cycle() -> JobResult:
    """REL-081: replaces the "TradingOS Daily Shadow Mode" Windows Scheduled Task (weekdays
    10:00 IST). Real per-broker Shadow Mode attempts, in-process -- see
    `src/api/routers/shadow_mode.py::run_one_shadow_mode_attempt`/`resolve_daily_shadow_mode_symbols`
    for the real logic (moved from `scripts/run_daily_shadow_mode.py`; no HTTP self-call or admin
    JWT needed now that this runs inside the same process as the endpoint it used to call)."""
    from src.api.routers.shadow_mode import (
        resolve_daily_shadow_mode_symbols,
        run_one_shadow_mode_attempt,
    )
    from src.brokers.base import OrderRequest
    from src.brokers.factory import NoBrokerConfigured

    try:
        broker_symbols = await resolve_daily_shadow_mode_symbols()
        outcomes: list[str] = []
        for broker, symbol in broker_symbols.items():
            if symbol is None:
                outcomes.append(f"{broker}: not configured, skipped")
                continue
            order = OrderRequest(symbol=symbol, side="BUY", order_type="MARKET", quantity=1)
            try:
                with get_session() as session:
                    row = await run_one_shadow_mode_attempt(session, broker=broker, order=order)
                outcomes.append(f"{broker}: {row.outcome} (real_sandbox={row.used_real_sandbox})")
            except NoBrokerConfigured:
                outcomes.append(f"{broker}: not configured, skipped")
        summary = "; ".join(outcomes) if outcomes else "no brokers configured"
        logger.info("scheduler_shadow_mode_daily_cycle_completed", summary=summary)
        return JobResult("Completed", summary)
    except Exception as exc:  # noqa: BLE001 - a failed cycle must not crash the app
        logger.warning("scheduler_shadow_mode_daily_cycle_failed", error=str(exc))
        return JobResult("Failed", str(exc))


def run_audit_archive_job() -> JobResult:
    """REL-081: replaces the "TradingOS Nightly Audit Archive" Windows Scheduled Task (23:30
    IST). Real WORM archive cycle, in-process -- see
    `src/core/audit_archive.py::archive_pending_rows` (moved from
    `scripts/archive_audit_log.py::main()`)."""
    from src.core.audit_archive import archive_pending_rows

    try:
        with get_session() as session:
            archived_count, failure_count = archive_pending_rows(session)
        summary = f"{archived_count} row(s) archived, {failure_count} failure(s)"
        status: Literal["Completed", "Failed"] = "Failed" if failure_count else "Completed"
        logger.info(
            "scheduler_audit_archive_completed",
            archived=archived_count,
            failures=failure_count,
        )
        return JobResult(status, summary)
    except Exception as exc:  # noqa: BLE001 - a failed archive pass must not crash the app
        logger.warning("scheduler_audit_archive_failed", error=str(exc))
        return JobResult("Failed", str(exc))


async def run_audit_chain_verification_job() -> JobResult:
    """REL-081: replaces the "TradingOS Audit Chain Verification" Windows Scheduled Task (02:00
    IST). Real hash-chain divergence check, in-process, read-only -- see
    `src/core/audit_chain_monitor.py`'s own module docstring. On divergence, fans out the same
    real Telegram/Discord/Slack alert `scripts/verify_audit_chain.py` always has."""
    from src.core.audit_chain_monitor import format_divergence_alert, run_divergence_check
    from src.core.ops_alerts import send_ops_alert

    try:
        with get_session() as session:
            report = run_divergence_check(session)
        if report.ok:
            summary = (
                f"chain OK: live {report.live.rows_checked} row(s), "
                f"archive {report.archived_rows_checked} row(s) checked, no divergence"
            )
            logger.info("scheduler_audit_chain_verification_completed", summary=summary)
            return JobResult("Completed", summary)

        message = format_divergence_alert(report)
        alert_failures = await send_ops_alert(message)
        if alert_failures:
            logger.warning(
                "scheduler_audit_chain_verification_alert_failed", channels=alert_failures
            )
        logger.warning("scheduler_audit_chain_verification_divergence_detected", message=message)
        return JobResult("Failed", message)
    except Exception as exc:  # noqa: BLE001 - a failed check must not crash the app
        logger.warning("scheduler_audit_chain_verification_failed", error=str(exc))
        return JobResult("Failed", str(exc))


def run_data_lake_backup_job() -> JobResult:
    """REL-081: replaces the "TradingOS Nightly Backup" Windows Scheduled Task (23:00 IST). Real
    Parquet snapshot + SHA-256 + DuckDB validation, in-process -- see
    `src/data/datalake/backup.py::run_backup_cycle` (moved from
    `scripts/backup_data_lake.py::main()`)."""
    from src.data.datalake.backup import run_backup_cycle

    try:
        result = run_backup_cycle(get_settings().data_lake_root)
        summary = (
            f"{result.files_backed_up}/{result.files_found} file(s) backed up "
            f"to {result.backup_root}"
        )
        status: Literal["Completed", "Failed"] = "Failed" if result.failures else "Completed"
        logger.info(
            "scheduler_data_lake_backup_completed",
            files_backed_up=result.files_backed_up,
            files_found=result.files_found,
        )
        return JobResult(status, summary)
    except Exception as exc:  # noqa: BLE001 - a failed backup pass must not crash the app
        logger.warning("scheduler_data_lake_backup_failed", error=str(exc))
        return JobResult("Failed", str(exc))


def run_duckdb_catalog_refresh_job() -> JobResult:
    """DB-022: keeps the DuckDB catalog views (src/data/datalake/catalog.py) matching whatever
    partitions currently exist in the lake -- `CREATE OR REPLACE VIEW` is idempotent, so running
    this on every tick even when nothing changed since the last run is safe and cheap."""
    from src.data.datalake.catalog import refresh_catalog_views

    try:
        result = refresh_catalog_views(get_settings().data_lake_root)
        summary = f"Refreshed {', '.join(result.views_created)} in {result.catalog_path}"
        logger.info("scheduler_duckdb_catalog_refresh_completed", catalog_path=result.catalog_path)
        return JobResult("Completed", summary)
    except Exception as exc:  # noqa: BLE001 - a failed refresh must not crash the app
        logger.warning("scheduler_duckdb_catalog_refresh_failed", error=str(exc))
        return JobResult("Failed", str(exc))


# --- REL-081: the real, editable schedule registry + execution tracking ------------------------


@dataclass(frozen=True)
class ScheduledJobSpec:
    job_id: str
    display_name: str
    description: str
    default_cron: str
    func: "Callable[[], JobResult] | Callable[[], Awaitable[JobResult]]"
    is_async: bool


JOB_REGISTRY: dict[str, ScheduledJobSpec] = {
    MARKET_DATA_INGESTION_JOB_ID: ScheduledJobSpec(
        job_id=MARKET_DATA_INGESTION_JOB_ID,
        display_name="Market Data Ingestion",
        description="Real scheduled incremental ingestion (REL-072) -- keeps the EOD data lake "
        "fresh before the daily research cycle's own freshness gate checks it.",
        default_cron="0 5 * * *",
        func=run_market_data_ingestion,
        is_async=False,
    ),
    CORPORATE_ACTIONS_JOB_ID: ScheduledJobSpec(
        job_id=CORPORATE_ACTIONS_JOB_ID,
        display_name="Corporate Actions Ingestion",
        description="Real CSV-read + Postgres upsert of split/bonus corporate actions "
        "(REL-010 E10.7), before the daily research cycle so a same-day action is reflected.",
        default_cron="30 5 * * *",
        func=run_corporate_actions_ingestion,
        is_async=False,
    ),
    DAILY_CYCLE_JOB_ID: ScheduledJobSpec(
        job_id=DAILY_CYCLE_JOB_ID,
        display_name="Daily Research Cycle",
        description="SRS Workflow 1 step 1 -- triggers the real CEO -> Market Analyst -> "
        "Strategy Generator -> Code Gen/Validator graph run, deferred on a stale data lake.",
        default_cron="0 6 * * *",
        func=run_daily_research_cycle,
        is_async=False,
    ),
    NEWS_SENTIMENT_JOB_ID: ScheduledJobSpec(
        job_id=NEWS_SENTIMENT_JOB_ID,
        display_name="News Sentiment Cycle",
        description="Real RSS ingestion + real LLM sentiment scoring persisted to Qdrant "
        "(REL-010 E10.3), every 30 minutes across NSE's real market-hours session.",
        default_cron="*/30 9-15 * * *",
        func=run_news_sentiment_cycle,
        is_async=False,
    ),
    WEEKEND_MEMORY_JOB_ID: ScheduledJobSpec(
        job_id=WEEKEND_MEMORY_JOB_ID,
        display_name="Weekend Memory Consolidation",
        description="Real Memory Agent weekend job (WF-06) -- archives low-confidence "
        "strategy-memory vectors and generates a real lessons-learned summary.",
        default_cron="0 2 * * sat",
        func=run_weekend_memory_consolidation,
        is_async=False,
    ),
    PAPER_TRADING_DAILY_CYCLE_JOB_ID: ScheduledJobSpec(
        job_id=PAPER_TRADING_DAILY_CYCLE_JOB_ID,
        display_name="Paper Trading Daily Cycle",
        description="REL-034 -- the once-per-trading-day directional signal for every strategy "
        "in PaperTrading status, after the research cycle and before market open.",
        default_cron="30 6 * * *",
        func=run_paper_trading_daily_cycle,
        is_async=True,
    ),
    PAPER_TRADING_EQUITY_SNAPSHOT_JOB_ID: ScheduledJobSpec(
        job_id=PAPER_TRADING_EQUITY_SNAPSHOT_JOB_ID,
        display_name="Paper Trading Equity Snapshot",
        description="REL-034 -- one real AccountEquitySnapshot row per trading day, ~5 minutes "
        "after NSE's real 15:30 IST close.",
        default_cron="35 15 * * *",
        func=run_paper_trading_equity_snapshot,
        is_async=True,
    ),
    SHADOW_MODE_DAILY_CYCLE_JOB_ID: ScheduledJobSpec(
        job_id=SHADOW_MODE_DAILY_CYCLE_JOB_ID,
        display_name="Shadow Mode Daily Cycle",
        description="REL-081 (was the 'TradingOS Daily Shadow Mode' Windows Scheduled Task) -- "
        "real per-broker Shadow Mode attempts, advancing the Go-Live Readiness Gate's "
        "consecutive-clean-days streak.",
        default_cron="0 10 * * mon-fri",
        func=run_shadow_mode_daily_cycle,
        is_async=True,
    ),
    AUDIT_ARCHIVE_JOB_ID: ScheduledJobSpec(
        job_id=AUDIT_ARCHIVE_JOB_ID,
        display_name="Nightly Audit Archive",
        description="REL-081 (was the 'TradingOS Nightly Audit Archive' Windows Scheduled Task) "
        "-- real WORM replication of audit_log rows older than 24h into the MinIO Object-Lock "
        "bucket (SEC-039).",
        default_cron="30 23 * * *",
        func=run_audit_archive_job,
        is_async=False,
    ),
    AUDIT_CHAIN_VERIFICATION_JOB_ID: ScheduledJobSpec(
        job_id=AUDIT_CHAIN_VERIFICATION_JOB_ID,
        display_name="Audit Chain Verification",
        description="REL-081 (was the 'TradingOS Audit Chain Verification' Windows Scheduled "
        "Task) -- real hash-chain divergence check (SEC-040), read-only, alerts on divergence.",
        default_cron="0 2 * * *",
        func=run_audit_chain_verification_job,
        is_async=True,
    ),
    DATA_LAKE_BACKUP_JOB_ID: ScheduledJobSpec(
        job_id=DATA_LAKE_BACKUP_JOB_ID,
        display_name="Nightly Data Lake Backup",
        description="REL-081 (was the 'TradingOS Nightly Backup' Windows Scheduled Task) -- "
        "real Parquet snapshot with SHA-256 + DuckDB checksum validation (Phase 1 E1.3).",
        default_cron="0 23 * * *",
        func=run_data_lake_backup_job,
        is_async=False,
    ),
    DUCKDB_CATALOG_REFRESH_JOB_ID: ScheduledJobSpec(
        job_id=DUCKDB_CATALOG_REFRESH_JOB_ID,
        display_name="DuckDB Catalog View Refresh",
        description="DB-022: keeps the persistent DuckDB catalog's ohlcv_daily/ohlcv_intraday "
        "views (src/data/datalake/catalog.py) matching the lake's current real partitions, so any "
        "DuckDB client can query them directly without going through the DataLake Python class.",
        default_cron="30 23 * * *",
        func=run_duckdb_catalog_refresh_job,
        is_async=False,
    ),
}


_scheduler_instance: AsyncIOScheduler | None = None


def get_running_scheduler() -> AsyncIOScheduler | None:
    """REL-081: the live, in-process APScheduler instance if this process actually started one
    (`Settings.run_scheduler`) -- `None` on the `app-tls` sibling (`RUN_SCHEDULER=false` by
    design, REL-007 E7.6) or before `build_scheduler()` has run. `src.api.routers.scheduled_jobs`
    uses this to reschedule/pause/resume a live job when its config is edited via the API, and
    to dispatch a real Run Now -- both need the actual running instance, not a fresh one, which
    is exactly why this is a module-level getter rather than a fresh `AsyncIOScheduler()` per
    call (matching this codebase's existing idiom for a shared runtime resource, e.g.
    `get_redis_client()`, rather than the `app.state.*` pattern this codebase doesn't use)."""
    return _scheduler_instance


def validate_cron_expression(cron_expression: str) -> bool:
    """Real validation via APScheduler's own crontab parser -- the same parser `build_scheduler`/
    `apply_schedule_change` actually use for the real trigger, so a value that validates here is
    guaranteed to work there too."""
    try:
        CronTrigger.from_crontab(cron_expression, timezone=IST_TIMEZONE)
    except ValueError:
        return False
    return True


def get_effective_schedule(job_id: str, *, session: Session | None = None) -> tuple[str, bool]:
    """Real `scheduled_job_config` override if one exists, else the job's own hardcoded
    `default_cron` -- the same fail-open convention this whole feature is built on. Returns
    `(cron_expression, enabled)`. Raises `KeyError` for an unknown `job_id` (callers -- the
    scheduled-jobs router -- already validate against `JOB_REGISTRY` before reaching here).
    Accepts an existing `session` (the router's own, looping over every `JOB_REGISTRY` entry for
    `GET /scheduled-jobs`) to avoid opening a fresh DB connection per job; opens its own when
    called standalone (`build_scheduler()` at process startup, once per job)."""
    spec = JOB_REGISTRY[job_id]

    def _query(s: Session) -> ScheduledJobConfig | None:
        return s.scalar(select(ScheduledJobConfig).where(ScheduledJobConfig.job_id == job_id))

    row = _query(session) if session is not None else None
    if session is None:
        with get_session() as owned_session:
            row = _query(owned_session)
    if row is None:
        return (spec.default_cron, True)
    return (row.cron_expression, row.enabled)


def apply_schedule_change(
    job_id: str,
    *,
    cron_expression: str | None,
    enabled: bool | None,
    updated_by_user_id: uuid.UUID | None = None,
) -> None:
    """REL-081: the real, single mutation path behind `PUT /scheduled-jobs/{job_id}` -- upserts
    the `scheduled_job_config` row, then, if a scheduler is actually running on this process,
    re-applies the change to the LIVE `AsyncIOScheduler` instance so it takes effect immediately,
    not just on the next restart. Caller (the router) has already validated `job_id` is a real
    `JOB_REGISTRY` key and `cron_expression` (if given) passes `validate_cron_expression`."""
    with get_session() as session:
        row = session.scalar(select(ScheduledJobConfig).where(ScheduledJobConfig.job_id == job_id))
        if row is None:
            spec = JOB_REGISTRY[job_id]
            row = ScheduledJobConfig(
                job_id=job_id,
                cron_expression=cron_expression or spec.default_cron,
                enabled=enabled if enabled is not None else True,
                updated_by_user_id=updated_by_user_id,
                updated_at=datetime.now(UTC),
            )
            session.add(row)
        else:
            if cron_expression is not None:
                row.cron_expression = cron_expression
            if enabled is not None:
                row.enabled = enabled
            row.updated_by_user_id = updated_by_user_id
            row.updated_at = datetime.now(UTC)
        session.commit()
        final_cron = row.cron_expression
        final_enabled = row.enabled

    scheduler = get_running_scheduler()
    if scheduler is None:
        return
    if cron_expression is not None:
        scheduler.reschedule_job(
            job_id, trigger=CronTrigger.from_crontab(final_cron, timezone=IST_TIMEZONE)
        )
    if enabled is not None:
        if final_enabled:
            scheduler.resume_job(job_id)
        else:
            scheduler.pause_job(job_id)


def _start_run(
    job_id: str,
    trigger_source: Literal["cron", "manual"],
    *,
    triggered_by_user_id: uuid.UUID | None = None,
) -> uuid.UUID:
    with get_session() as session:
        row = ScheduledJobRun(
            job_id=job_id,
            trigger_source=trigger_source,
            status="Running",
            started_at=datetime.now(UTC),
            triggered_by_user_id=triggered_by_user_id,
        )
        session.add(row)
        session.commit()
        return row.id


def _finish_run(run_id: uuid.UUID, result: JobResult) -> None:
    with get_session() as session:
        row = session.get(ScheduledJobRun, run_id)
        if row is not None:
            row.status = result.status
            row.ended_at = datetime.now(UTC)
            row.result_summary = result.summary[:4000]
            session.commit()


def _tracked(
    job_id: str,
    trigger_source: Literal["cron", "manual"],
    func: Callable[[], JobResult],
    *,
    run_id: uuid.UUID | None = None,
) -> Callable[[], None]:
    """REL-081: wraps a sync job function so every real firing writes a real `ScheduledJobRun`
    row -- `run_id` lets a caller that already created the `Running` row (the Run Now endpoint,
    so it can return a real id immediately) reuse it instead of a second row being created here.
    Reused identically for both a cron fire and a Run Now dispatch -- no second, subtly-different
    code path for manual runs."""

    def run() -> None:
        actual_run_id = run_id if run_id is not None else _start_run(job_id, trigger_source)
        try:
            result = func()
        except Exception as exc:  # noqa: BLE001 -- a real escape past the function's own catch-all
            result = JobResult("Failed", f"unhandled exception: {exc}")
        _finish_run(actual_run_id, result)

    return run


def _tracked_async(
    job_id: str,
    trigger_source: Literal["cron", "manual"],
    func: Callable[[], Awaitable[JobResult]],
    *,
    run_id: uuid.UUID | None = None,
) -> Callable[[], Awaitable[None]]:
    """Async twin of `_tracked` above -- same shape, `await`s the real job function."""

    async def run() -> None:
        actual_run_id = run_id if run_id is not None else _start_run(job_id, trigger_source)
        try:
            result = await func()
        except Exception as exc:  # noqa: BLE001
            result = JobResult("Failed", f"unhandled exception: {exc}")
        _finish_run(actual_run_id, result)

    return run


def dispatch_manual_run(job_id: str, *, triggered_by_user_id: uuid.UUID) -> uuid.UUID | None:
    """REL-081: real "Run Now" dispatch behind `POST /scheduled-jobs/{job_id}/run-now` -- reuses
    the live `AsyncIOScheduler` instance and the exact same `_tracked`/`_tracked_async` wrappers
    a cron fire uses, via a `DateTrigger` firing once, right now, instead of the job's own cron
    -- same executor, same async/sync handling as a real scheduled fire, not a second dispatch
    mechanism. Returns `None` if no live scheduler is reachable on this process (the router maps
    that to a real 503); caller has already validated `job_id` against `JOB_REGISTRY`."""
    scheduler = get_running_scheduler()
    if scheduler is None:
        return None
    spec = JOB_REGISTRY[job_id]
    run_id = _start_run(job_id, "manual", triggered_by_user_id=triggered_by_user_id)
    wrapped = (
        _tracked_async(
            job_id,
            "manual",
            cast("Callable[[], Awaitable[JobResult]]", spec.func),
            run_id=run_id,
        )
        if spec.is_async
        else _tracked(job_id, "manual", cast("Callable[[], JobResult]", spec.func), run_id=run_id)
    )
    scheduler.add_job(
        wrapped,
        DateTrigger(),
        id=f"{job_id}-manual-{uuid.uuid4().hex[:8]}",
        misfire_grace_time=3600,
    )
    return run_id


def build_scheduler() -> AsyncIOScheduler:
    global _scheduler_instance
    scheduler = AsyncIOScheduler(timezone=IST_TIMEZONE)
    for job_id, spec in JOB_REGISTRY.items():
        cron_expression, enabled = get_effective_schedule(job_id)
        trigger = CronTrigger.from_crontab(cron_expression, timezone=IST_TIMEZONE)
        wrapped = (
            _tracked_async(job_id, "cron", cast("Callable[[], Awaitable[JobResult]]", spec.func))
            if spec.is_async
            else _tracked(job_id, "cron", cast("Callable[[], JobResult]", spec.func))
        )
        scheduler.add_job(wrapped, trigger, id=job_id, replace_existing=True)
        if not enabled:
            scheduler.pause_job(job_id)
    _scheduler_instance = scheduler
    return scheduler
