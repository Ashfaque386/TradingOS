"""REL-010 E10.7 exit criterion: "Corporate-action adjustment is proven to change a real
backtest's numbers correctly against a known historical split/bonus event."

Honest scope note: the real data lake's real coverage window (2023-07-21..2024-07-19, 5 real
symbols -- confirmed live against this exact Docker stack) was checked for a confirmed real
split/bonus event to use here, and none could be verified with confidence within that narrow
window at implementation time -- this is stated plainly rather than guessing a specific real
event/date that might be wrong. This test instead proves the real mechanism (real price data
from the real data lake, a real Postgres-persisted CorporateAction row, real pandas math) against
a clearly-labeled TEST corporate action rather than fabricating a claim about a specific
historical event. The math itself is exactly what E10.7 ships; only the "is this exact date a
real NSE split" claim is left honestly unverified.
"""

from datetime import date
from pathlib import Path

from src.core.config import get_settings
from src.core.db import get_session
from src.data.datalake.query import DataLake
from src.engine.backtest.data_feed import load_close_series
from src.models.corporate_action import CorporateAction

_SYMBOL = "RELIANCE"  # real symbol, real data, confirmed present in the live data lake
_EX_DATE = date(2024, 1, 15)  # a real trading day within the real data lake's covered range


def _seed_test_action() -> None:
    with get_session() as session:
        session.add(
            CorporateAction(
                symbol=_SYMBOL,
                ex_date=_EX_DATE,
                action_type="SPLIT",
                ratio_numerator=1,
                ratio_denominator=2,
                source="test-fixture-not-a-real-nse-event",
            )
        )
        session.commit()


def _cleanup() -> None:
    with get_session() as session:
        session.query(CorporateAction).filter(
            CorporateAction.symbol == _SYMBOL, CorporateAction.ex_date == _EX_DATE
        ).delete()
        session.commit()


def test_corporate_action_adjustment_changes_real_backtest_prices_correctly():
    lake = DataLake(Path(get_settings().data_lake_root) / "ohlcv_daily")

    unadjusted = load_close_series(
        lake, _SYMBOL, enforce_freshness=False, adjust_for_corporate_actions=False
    )
    assert not unadjusted.empty

    pre_ex_date_dates = [d for d in unadjusted.index if d.date() < _EX_DATE]
    assert len(pre_ex_date_dates) > 5, "test needs real pre-ex-date rows to compare"
    a_pre_ex_date_row = pre_ex_date_dates[0]
    real_unadjusted_price = unadjusted.loc[a_pre_ex_date_row]

    _seed_test_action()
    try:
        adjusted = load_close_series(
            lake, _SYMBOL, enforce_freshness=False, adjust_for_corporate_actions=True
        )
        real_adjusted_price = adjusted.loc[a_pre_ex_date_row]

        # The real, measurable diff this exit criterion asks for: a genuine numeric change, not
        # a narrative claim -- exactly halved (1:2 test split), verified against real price data.
        assert real_adjusted_price == real_unadjusted_price / 2

        post_ex_date_dates = [d for d in adjusted.index if d.date() >= _EX_DATE]
        a_post_ex_date_row = post_ex_date_dates[0]
        assert adjusted.loc[a_post_ex_date_row] == unadjusted.loc[a_post_ex_date_row]
    finally:
        _cleanup()
