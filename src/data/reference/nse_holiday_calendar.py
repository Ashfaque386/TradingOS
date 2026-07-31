"""Real NSE trading-holiday calendar (REL-010 E10.7), replacing the "every weekday is a
trading day" approximation duplicated in src/data/ingest/bhavcopy.py::_trading_days and
src/data/datalake/freshness.py::previous_trading_day (both explicitly flagged in their own
comments as temporary).

Honest, deliberate scope limit (same class of gap as compliance_checker.py's
PLACEHOLDER_SEBI_POSITION_LIMITS -- a real, dated, hand-maintained reference table, not a live
feed): only the 3 fixed-date national holidays NSE always observes are included --
Republic Day (Jan 26), Independence Day (Aug 15), Gandhi Jayanti (Oct 2). NSE's real annual
calendar also includes ~7-8 movable holidays (Holi, Good Friday, Ram Navami, Eid, Diwali,
Dussehra, Guru Nanak Jayanti, etc.) whose exact dates shift every year with the lunar/religious
calendar -- no confirmed, verified source for those exact dates existed at REL-010
implementation time, so they are deliberately NOT guessed here. This module is a real, measurable
improvement over "every weekday" (it now correctly excludes 3 real trading holidays per year
instead of 0), not a claim of full calendar coverage -- `HOLIDAYS` needs a real annual refresh
and movable-holiday additions from NSE's own published circular, same as the SEBI table.
"""

from datetime import date, timedelta

# Fixed-date national holidays only (see module docstring). Covers the real data lake's own
# date range (2023-07-21..2024-07-19) plus the years either side of "today" in this session
# (2026-07-31), for correctness anywhere a caller might be doing forward/backward date math.
HOLIDAYS: frozenset[date] = frozenset(
    {
        date(2023, 1, 26),
        date(2023, 8, 15),
        date(2023, 10, 2),
        date(2024, 1, 26),
        date(2024, 8, 15),
        date(2024, 10, 2),
        date(2025, 1, 26),
        date(2025, 8, 15),
        date(2025, 10, 2),
        date(2026, 1, 26),
        date(2026, 8, 15),
        date(2026, 10, 2),
        date(2027, 1, 26),
        date(2027, 8, 15),
        date(2027, 10, 2),
    }
)


def is_trading_holiday(d: date) -> bool:
    """True for a real, known NSE trading holiday OR a weekend -- callers that only want the
    holiday check itself (already handling weekends separately) should check `d in HOLIDAYS`
    directly instead."""
    return d.weekday() >= 5 or d in HOLIDAYS


def previous_trading_day(as_of: date) -> date:
    day = as_of - timedelta(days=1)
    while is_trading_holiday(day):
        day -= timedelta(days=1)
    return day


def next_trading_day(as_of: date) -> date:
    day = as_of + timedelta(days=1)
    while is_trading_holiday(day):
        day += timedelta(days=1)
    return day


def trading_days_between(start: date, end: date) -> list[date]:
    """Inclusive of both ends -- real replacement for bhavcopy.py's own `_trading_days`."""
    days = []
    current = start
    while current <= end:
        if not is_trading_holiday(current):
            days.append(current)
        current += timedelta(days=1)
    return days
