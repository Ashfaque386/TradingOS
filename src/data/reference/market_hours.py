"""Shared real NSE/BSE cash-market session check (09:15-15:30 IST), factored out of
`src/workers/tick_publisher.py`'s own inline `_is_market_open` (REL-034) so the paper trading
worker (`src/workers/paper_trading_worker.py`) shares the exact same check rather than a second,
possibly-drifting copy of the same three conditions (weekday, real NSE holiday, session window).
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from src.data.reference.nse_holiday_calendar import is_trading_holiday

IST = ZoneInfo("Asia/Kolkata")

# Matches src/agents/scheduler.py's own news/sentiment cron window.
MARKET_OPEN_MINUTES = 9 * 60 + 15
MARKET_CLOSE_MINUTES = 15 * 60 + 30


def is_market_open(now_ist: datetime | None = None) -> bool:
    now_ist = now_ist or datetime.now(IST)
    if now_ist.weekday() >= 5:  # Monday=0 .. Saturday=5, Sunday=6
        return False
    if is_trading_holiday(now_ist.date()):
        return False
    now_minutes = now_ist.hour * 60 + now_ist.minute
    return MARKET_OPEN_MINUTES <= now_minutes <= MARKET_CLOSE_MINUTES
