"""Dataset freshness as a first-class organisational fact (spec T085/T088, data-model.md §11,
FR-060..064, BUG-A).

``record_ingestion_result`` is the single write path: an ingestion run reports whether it
succeeded, passed checksum/structural validation, and produced real rows. Only
``success and checksum_ok and has_data`` ever sets ``status = "fresh"`` -- anything else is
``failed`` or ``unavailable`` and raises an ops alert on the transition. No caller may
substitute synthetic data to make a dataset look fresh (FR-063).

``is_fresh`` is what the planner / task engine ask before dispatching a dataset-dependent task
(FR-061/062): ``status == "fresh"`` **and** the record is still within its cadence window --
staleness can also happen purely from the passage of time, with no new ingestion attempt.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.data.reference.nse_holiday_calendar import previous_trading_day
from src.models.dataset_freshness import DatasetFreshnessRecord
from src.orchestration.enums import DatasetFreshnessStatus

logger = structlog.get_logger(__name__)

# dataset_name -> (cadence, freshness_rule, "daily" | "intraday")
KNOWN_DATASETS: dict[str, tuple[str, str, str]] = {
    "ohlcv_daily": (
        "nightly after NSE close on trading days",
        "fresh if last successful update covers the previous trading day",
        "daily",
    ),
    "instrument_master": (
        "weekly",
        "fresh if updated within the last 7 days",
        "weekly",
    ),
    "corporate_actions": (
        "nightly after NSE close on trading days",
        "fresh if last successful update covers the previous trading day",
        "daily",
    ),
    "news": (
        "every 30 minutes during market hours",
        "fresh if updated within the last 2 hours",
        "intraday",
    ),
    "nse_index_ohlcv": (
        "nightly after NSE close on trading days",
        "fresh if last successful update covers the previous trading day",
        "daily",
    ),
}


def ensure_seeded(session: Session) -> None:
    """Insert an ``unavailable`` row for every known dataset that has none yet. Idempotent."""
    existing = set(session.scalars(select(DatasetFreshnessRecord.dataset_name)).all())
    now = datetime.now(UTC)
    for name, (cadence, rule, _) in KNOWN_DATASETS.items():
        if name in existing:
            continue
        session.add(
            DatasetFreshnessRecord(
                dataset_name=name,
                cadence=cadence,
                freshness_rule=rule,
                status=DatasetFreshnessStatus.UNAVAILABLE.value,
                retry_state={},
                updated_at=now,
            )
        )
    session.flush()


def _get_or_create(session: Session, dataset_name: str) -> DatasetFreshnessRecord:
    row = session.scalars(
        select(DatasetFreshnessRecord).where(DatasetFreshnessRecord.dataset_name == dataset_name)
    ).first()
    if row is not None:
        return row
    cadence, rule, _ = KNOWN_DATASETS.get(
        dataset_name, ("unknown", "no freshness rule registered for this dataset", "daily")
    )
    row = DatasetFreshnessRecord(
        dataset_name=dataset_name,
        cadence=cadence,
        freshness_rule=rule,
        status=DatasetFreshnessStatus.UNAVAILABLE.value,
        retry_state={},
        updated_at=datetime.now(UTC),
    )
    session.add(row)
    session.flush()
    return row


def _alert(message: str) -> None:
    try:
        from src.core.ops_alerts import send_ops_alert

        asyncio.run(send_ops_alert(message))
    except Exception as exc:  # noqa: BLE001 -- an alert-delivery hiccup must never break ingestion
        logger.warning("dataset_freshness_alert_failed", error=str(exc))


def record_ingestion_result(
    session: Session,
    dataset_name: str,
    *,
    success: bool,
    checksum_ok: bool,
    has_data: bool,
    detail: str | None = None,
) -> DatasetFreshnessRecord:
    """The single write path for a dataset's freshness. ``status`` becomes ``fresh`` only when
    all three of ``success``, ``checksum_ok``, ``has_data`` hold (FR-064) -- never a fabricated
    pass, and never a synthetic backfill on this path (FR-063)."""
    row = _get_or_create(session, dataset_name)
    before_status = row.status
    now = datetime.now(UTC)

    if success and checksum_ok and has_data:
        row.status = DatasetFreshnessStatus.FRESH.value
        row.last_successful_update = now
        row.last_checksum_ok = True
        row.retry_state = {}
    else:
        row.status = (
            DatasetFreshnessStatus.FAILED.value
            if success
            else DatasetFreshnessStatus.UNAVAILABLE.value
        )
        row.last_checksum_ok = checksum_ok if success else row.last_checksum_ok
        retries = dict(row.retry_state or {})
        retries["consecutive_failures"] = int(retries.get("consecutive_failures", 0)) + 1
        retries["last_detail"] = detail or "ingestion did not produce valid, checked data"
        row.retry_state = retries
    row.updated_at = now
    session.flush()

    if before_status != row.status:
        event_type = (
            "dataset.refreshed"
            if row.status == DatasetFreshnessStatus.FRESH.value
            else (
                "dataset.ingestion_failed"
                if row.status == DatasetFreshnessStatus.FAILED.value
                else "dataset.stale"
            )
        )
        logger.info(
            "dataset_freshness_transition",
            dataset=dataset_name,
            from_status=before_status,
            to_status=row.status,
            event_type=event_type,
        )
        if row.status in (
            DatasetFreshnessStatus.FAILED.value,
            DatasetFreshnessStatus.UNAVAILABLE.value,
        ):
            _alert(
                f"[TradingOS] dataset '{dataset_name}' is now {row.status}: "
                f"{detail or 'ingestion did not pass validation'}"
            )
    return row


def _within_cadence(row: DatasetFreshnessRecord, dataset_name: str) -> bool:
    if row.last_successful_update is None:
        return False
    last = row.last_successful_update
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    _, _, cadence_kind = KNOWN_DATASETS.get(dataset_name, ("", "", "daily"))
    now = datetime.now(UTC)
    if cadence_kind == "intraday":
        return (now - last) <= timedelta(hours=2)
    if cadence_kind == "weekly":
        return (now - last) <= timedelta(days=7)
    # "daily": fresh only if the last successful update covers the previous trading day.
    expected = previous_trading_day(date.today())
    return last.date() >= expected


def is_fresh(session: Session, dataset_name: str) -> bool:
    """FR-061/062: what the planner / task engine ask before dispatching a dataset-dependent
    task. ``False`` for an unknown dataset -- never assumed fresh."""
    row = session.scalars(
        select(DatasetFreshnessRecord).where(DatasetFreshnessRecord.dataset_name == dataset_name)
    ).first()
    if row is None or row.status != DatasetFreshnessStatus.FRESH.value:
        return False
    return _within_cadence(row, dataset_name)


def snapshot(session: Session) -> list[dict[str, Any]]:
    """Every tracked dataset's current freshness -- for the console (T088/T089)."""
    ensure_seeded(session)
    rows = session.scalars(
        select(DatasetFreshnessRecord).order_by(DatasetFreshnessRecord.dataset_name)
    ).all()
    return [
        {
            "dataset_name": r.dataset_name,
            "cadence": r.cadence,
            "status": r.status,
            "last_successful_update": (
                r.last_successful_update.isoformat() if r.last_successful_update else None
            ),
            "last_checksum_ok": r.last_checksum_ok,
        }
        for r in rows
    ]
