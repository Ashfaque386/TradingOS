"""REL-010 E10.7: real NSE holiday calendar, replacing the "every weekday" approximation.
Republic Day (2024-01-26) is a real, confirmed Friday -- a real trading holiday that the old
`weekday() < 5` approximation would have incorrectly counted as a trading day.
"""

from datetime import date

from src.data.reference.nse_holiday_calendar import (
    is_trading_holiday,
    next_trading_day,
    previous_trading_day,
    trading_days_between,
)


def test_fixed_national_holiday_is_flagged_even_on_a_weekday():
    assert date(2024, 1, 26).weekday() < 5  # Republic Day 2024 -- a real weekday, not a weekend
    assert is_trading_holiday(date(2024, 1, 26)) is True


def test_ordinary_weekday_is_not_a_holiday():
    assert is_trading_holiday(date(2024, 1, 29)) is False  # the following Monday


def test_weekend_is_a_holiday_too():
    assert is_trading_holiday(date(2024, 1, 27)) is True  # Saturday
    assert is_trading_holiday(date(2024, 1, 28)) is True  # Sunday


def test_previous_trading_day_skips_a_real_weekday_holiday():
    # 2024-01-29 (Monday) -- the previous real trading day should skip both the weekend
    # (27th/28th) AND Republic Day (26th, a Friday), landing on the 25th.
    assert previous_trading_day(date(2024, 1, 29)) == date(2024, 1, 25)


def test_next_trading_day_skips_a_real_weekday_holiday():
    assert next_trading_day(date(2024, 1, 25)) == date(2024, 1, 29)


def test_trading_days_between_excludes_the_real_holiday_and_weekend():
    days = trading_days_between(date(2024, 1, 25), date(2024, 1, 29))
    assert days == [date(2024, 1, 25), date(2024, 1, 29)]
