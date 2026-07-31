"""REL-010 E10.7: real CSV-read + real Postgres upsert for corporate_actions."""

from pathlib import Path

from sqlalchemy import select

from src.core.db import get_session
from src.data.ingest.corporate_actions import CorporateActionsAdapter, CorporateActionsWriter
from src.models.corporate_action import CorporateAction

_SYMBOL = "TESTSYMBOL-E10.7"


def _cleanup() -> None:
    with get_session() as session:
        session.query(CorporateAction).filter(CorporateAction.symbol == _SYMBOL).delete()
        session.commit()


def test_adapter_reads_a_real_csv_file(tmp_path: Path):
    csv_path = tmp_path / "corporate_actions.csv"
    csv_path.write_text(
        "symbol,ex_date,action_type,ratio_numerator,ratio_denominator,dividend_amount,source\n"
        f"{_SYMBOL},2024-03-01,SPLIT,1,2,,test-source\n"
    )
    rows = CorporateActionsAdapter(csv_path).fetch()
    assert len(rows) == 1
    assert rows[0]["symbol"] == _SYMBOL
    assert rows[0]["action_type"] == "SPLIT"


def test_adapter_returns_empty_list_for_a_missing_file(tmp_path: Path):
    assert CorporateActionsAdapter(tmp_path / "does-not-exist.csv").fetch() == []


def test_writer_upserts_into_real_postgres_idempotently(tmp_path: Path):
    csv_path = tmp_path / "corporate_actions.csv"
    csv_path.write_text(
        "symbol,ex_date,action_type,ratio_numerator,ratio_denominator,dividend_amount,source\n"
        f"{_SYMBOL},2024-03-01,SPLIT,1,2,,test-source\n"
        f"{_SYMBOL},2024-06-01,DIVIDEND,,,5.50,test-source\n"
    )
    rows = CorporateActionsAdapter(csv_path).fetch()

    try:
        with get_session() as session:
            first_run_written = CorporateActionsWriter().write(session, rows)
        assert first_run_written == 2

        with get_session() as session:
            second_run_written = CorporateActionsWriter().write(session, rows)
        assert second_run_written == 0  # idempotent -- both rows already exist

        with get_session() as session:
            db_rows = session.scalars(
                select(CorporateAction).where(CorporateAction.symbol == _SYMBOL)
            ).all()
        assert len(db_rows) == 2
        split_row = next(r for r in db_rows if r.action_type == "SPLIT")
        assert float(split_row.ratio_numerator) == 1.0
        assert float(split_row.ratio_denominator) == 2.0
        dividend_row = next(r for r in db_rows if r.action_type == "DIVIDEND")
        assert float(dividend_row.dividend_amount) == 5.50
    finally:
        _cleanup()
