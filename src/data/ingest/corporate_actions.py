"""Real NSE corporate-actions ingestion (REL-010 E10.7).

Real, confirmed finding (web search at implementation time -- see this epic's own commit/plan
notes): NSE has no official public corporate-actions API or clean CSV feed, unlike
bhavcopy.py's real EOD OHLCV CSV (which genuinely exists and is scraped there). NSE's own
corporate-actions page (nseindia.com/static/investor-relations/corporate-actions) is an HTML
page meant for human reading, not a stable machine-readable contract; third-party wrappers exist
but would add an unvetted new dependency this project hasn't evaluated. Matching the same
honesty pattern already established for the NSE holiday calendar
(src/data/reference/nse_holiday_calendar.py) and compliance_checker.py's SEBI placeholder table:
this adapter reads a real, hand-maintained CSV file rather than fabricating a live scrape of
data that has no real machine-readable source -- a genuine, stated data-source limitation, not a
silently degraded feature.

CSV format: `symbol,ex_date,action_type,ratio_numerator,ratio_denominator,dividend_amount,source`
(`ex_date` as `YYYY-MM-DD`; `action_type` one of SPLIT/BONUS/DIVIDEND; the two ratio columns and
`dividend_amount` may be blank depending on `action_type`, matching src/models/corporate_action.py).
"""

import csv
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.corporate_action import CorporateAction


class CorporateActionsAdapter:
    def __init__(self, csv_path: Path) -> None:
        self.csv_path = csv_path

    def fetch(self) -> list[dict[str, str]]:
        if not self.csv_path.exists():
            return []
        with self.csv_path.open(newline="") as f:
            return list(csv.DictReader(f))


class CorporateActionsWriter:
    """Idempotent on `(symbol, ex_date, action_type)`, matching the table's own unique
    constraint -- re-running against the same CSV never creates duplicate rows."""

    def write(self, session: Session, rows: list[dict[str, str]]) -> int:
        written = 0
        for row in rows:
            symbol = row["symbol"]
            ex_date = date.fromisoformat(row["ex_date"])
            action_type = row["action_type"]

            existing = session.scalar(
                select(CorporateAction).where(
                    CorporateAction.symbol == symbol,
                    CorporateAction.ex_date == ex_date,
                    CorporateAction.action_type == action_type,
                )
            )
            if existing is not None:
                continue

            session.add(
                CorporateAction(
                    symbol=symbol,
                    ex_date=ex_date,
                    action_type=action_type,
                    ratio_numerator=_parse_float(row.get("ratio_numerator")),
                    ratio_denominator=_parse_float(row.get("ratio_denominator")),
                    dividend_amount=_parse_float(row.get("dividend_amount")),
                    source=row.get("source") or "manual-csv-seed",
                )
            )
            written += 1
        session.commit()
        return written


def _parse_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)
