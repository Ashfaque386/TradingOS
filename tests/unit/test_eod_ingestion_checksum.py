"""Checksum/structural validation gate (spec T091, FR-064): an ingestion result is only ever
``fresh`` when it succeeded, passed checksum/structural validation, and produced real data. A
corrupt or failed run never gets to claim ``fresh`` -- and nothing here fabricates a substitute.
"""

from sqlalchemy import select

from src.core.db import get_session
from src.models.dataset_freshness import DatasetFreshnessRecord
from src.orchestration import freshness

_DATASET = "ohlcv_daily"


def _cleanup() -> None:
    with get_session() as session:
        session.query(DatasetFreshnessRecord).filter(
            DatasetFreshnessRecord.dataset_name == _DATASET
        ).delete()
        session.commit()


def test_a_clean_run_marks_the_dataset_fresh():
    _cleanup()
    try:
        with get_session() as session:
            row = freshness.record_ingestion_result(
                session, _DATASET, success=True, checksum_ok=True, has_data=True
            )
            session.commit()
            assert row.status == "fresh"
            assert row.last_checksum_ok is True
            assert row.last_successful_update is not None
        with get_session() as session:
            assert freshness.is_fresh(session, _DATASET) is True
    finally:
        _cleanup()


def test_a_run_with_per_symbol_failures_never_claims_fresh():
    _cleanup()
    try:
        with get_session() as session:
            row = freshness.record_ingestion_result(
                session,
                _DATASET,
                success=True,
                checksum_ok=False,
                has_data=False,
                detail="3 symbol(s) failed structural validation",
            )
            session.commit()
            assert row.status == "failed"
            assert row.status != "fresh"
        with get_session() as session:
            assert freshness.is_fresh(session, _DATASET) is False
    finally:
        _cleanup()


def test_a_total_ingestion_failure_marks_the_dataset_unavailable_not_fresh():
    _cleanup()
    try:
        with get_session() as session:
            row = freshness.record_ingestion_result(
                session,
                _DATASET,
                success=False,
                checksum_ok=False,
                has_data=False,
                detail="provider unreachable",
            )
            session.commit()
            assert row.status == "unavailable"
        with get_session() as session:
            assert freshness.is_fresh(session, _DATASET) is False
    finally:
        _cleanup()


def test_no_synthetic_row_is_ever_written_on_a_failed_run():
    _cleanup()
    try:
        with get_session() as session:
            before = session.scalars(
                select(DatasetFreshnessRecord).where(
                    DatasetFreshnessRecord.dataset_name == _DATASET
                )
            ).first()
            assert before is None
            freshness.record_ingestion_result(
                session, _DATASET, success=False, checksum_ok=False, has_data=False
            )
            session.commit()
        with get_session() as session:
            rows = session.scalars(
                select(DatasetFreshnessRecord).where(
                    DatasetFreshnessRecord.dataset_name == _DATASET
                )
            ).all()
            # exactly the one bookkeeping row -- no fabricated OHLCV/reference data anywhere.
            assert len(rows) == 1
            assert rows[0].last_successful_update is None
    finally:
        _cleanup()
