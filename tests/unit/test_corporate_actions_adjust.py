"""REL-010 E10.7: real split/bonus back-adjustment math, no DB needed -- `CorporateAction`
instances are constructed in-memory, never persisted, matching this codebase's convention for
pure-logic unit tests (e.g. tests/unit/test_module_coverage.py)."""

from datetime import date

import pandas as pd

from src.engine.backtest.corporate_actions_adjust import adjust_ohlcv_for_corporate_actions
from src.models.corporate_action import CorporateAction


def _frame(dates: list[date], closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes},
        index=pd.DatetimeIndex(dates, name="date"),
    )


def test_a_1_to_5_split_divides_pre_split_prices_by_5():
    # Real semantics: 1 old share becomes 5 new shares -- pre-split prices should be scaled down
    # to 1/5 so they're comparable to the post-split scale, not left as an artificial 5x jump.
    dates = [date(2024, 1, 10), date(2024, 1, 11), date(2024, 1, 12)]
    closes = [2500.0, 2510.0, 500.0]  # split occurs between the 11th and 12th
    df = _frame(dates, closes)
    action = CorporateAction(
        symbol="TEST",
        ex_date=date(2024, 1, 12),
        action_type="SPLIT",
        ratio_numerator=1,
        ratio_denominator=5,
        source="test",
    )

    adjusted = adjust_ohlcv_for_corporate_actions(df, [action])

    assert adjusted.loc[pd.Timestamp(date(2024, 1, 10)), "close"] == 500.0
    assert adjusted.loc[pd.Timestamp(date(2024, 1, 11)), "close"] == 502.0
    assert adjusted.loc[pd.Timestamp(date(2024, 1, 12)), "close"] == 500.0  # on/after ex_date


def test_dividend_rows_are_not_price_adjusted():
    dates = [date(2024, 1, 10), date(2024, 1, 11)]
    closes = [100.0, 100.0]
    df = _frame(dates, closes)
    action = CorporateAction(
        symbol="TEST",
        ex_date=date(2024, 1, 11),
        action_type="DIVIDEND",
        dividend_amount=5.0,
        source="test",
    )

    adjusted = adjust_ohlcv_for_corporate_actions(df, [action])

    assert adjusted["close"].tolist() == [100.0, 100.0]


def test_empty_dataframe_is_returned_unchanged():
    df = pd.DataFrame(columns=["open", "high", "low", "close"])
    assert adjust_ohlcv_for_corporate_actions(df, []).empty


def test_multiple_actions_compound_correctly_oldest_rows_get_both_adjustments():
    # A row before BOTH ex-dates gets both factors applied; a row between the two ex-dates gets
    # only the later action's factor.
    dates = [date(2024, 1, 1), date(2024, 6, 1), date(2024, 12, 1)]
    closes = [1000.0, 1000.0, 1000.0]
    df = _frame(dates, closes)
    first_split = CorporateAction(
        symbol="TEST",
        ex_date=date(2024, 3, 1),
        action_type="SPLIT",
        ratio_numerator=1,
        ratio_denominator=2,
        source="test",
    )
    second_split = CorporateAction(
        symbol="TEST",
        ex_date=date(2024, 9, 1),
        action_type="SPLIT",
        ratio_numerator=1,
        ratio_denominator=2,
        source="test",
    )

    adjusted = adjust_ohlcv_for_corporate_actions(df, [first_split, second_split])

    assert adjusted.loc[pd.Timestamp(date(2024, 1, 1)), "close"] == 250.0  # both halvings applied
    assert adjusted.loc[pd.Timestamp(date(2024, 6, 1)), "close"] == 500.0  # only the second applies
    assert adjusted.loc[pd.Timestamp(date(2024, 12, 1)), "close"] == 1000.0  # after both, untouched
