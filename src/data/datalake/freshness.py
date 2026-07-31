"""Enforces SRS Business Rule 4 (Data Freshness): backtests cannot run if the
data lake is missing the previous trading day's EOD data."""

from dataclasses import dataclass
from datetime import date

from src.data.datalake.query import DataLake
from src.data.reference.nse_holiday_calendar import previous_trading_day as _previous_trading_day


def previous_trading_day(as_of: date) -> date:
    """REL-010 E10.7: now a real NSE holiday calendar
    (src/data/reference/nse_holiday_calendar.py) rather than the "every weekday" approximation
    this function used to be -- see that module's own docstring for what real holidays are (and
    are not yet) covered. Re-exported under this same name so every existing call site
    (src/engine/backtest/, etc.) is unaffected."""
    return _previous_trading_day(as_of)


@dataclass(frozen=True)
class FreshnessResult:
    symbol: str
    is_fresh: bool
    expected_date: date
    latest_available: date | None


def check_freshness(lake: DataLake, symbol: str, as_of: date) -> FreshnessResult:
    expected = previous_trading_day(as_of)
    latest = lake.latest_date(symbol)
    return FreshnessResult(
        symbol=symbol,
        is_fresh=latest is not None and latest >= expected,
        expected_date=expected,
        latest_available=latest,
    )


class DataFreshnessError(RuntimeError):
    pass


def require_fresh(lake: DataLake, symbols: list[str], as_of: date) -> None:
    """Raises DataFreshnessError if any symbol's data lake copy is stale. Call before backtests."""
    stale = [check_freshness(lake, s, as_of) for s in symbols]
    stale = [r for r in stale if not r.is_fresh]
    if stale:
        details = ", ".join(
            f"{r.symbol} (latest={r.latest_available}, expected>={r.expected_date})" for r in stale
        )
        raise DataFreshnessError(f"Data lake is stale for: {details}")
