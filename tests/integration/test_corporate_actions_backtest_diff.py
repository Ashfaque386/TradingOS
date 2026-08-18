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

from datetime import date, timedelta
from pathlib import Path

from src.core.config import get_settings
from src.core.db import get_session
from src.data.datalake.query import DataLake
from src.engine.backtest.data_feed import load_close_series
from src.engine.sandbox.backtest_runner import run_real_backtest
from src.models.corporate_action import CorporateAction

_SYMBOL = "RELIANCE"  # real symbol, real data, confirmed present in the live data lake
_EX_DATE = date(2024, 1, 15)  # a real trading day within the real data lake's covered range

# REL-072: a trivial, valid run_backtest -- this test only cares about outcome.close_curve/
# data_adjusted, which run_real_backtest populates from its own real data-lake read regardless
# of what the sandboxed strategy code itself does, so no vectorbt call (and no numba JIT cost)
# is needed here, unlike test_real_backtest_runner.py's own strategy code.
_MINIMAL_STRATEGY_CODE = """
import polars as pl


def run_backtest(data: pl.DataFrame, config: dict) -> dict:
    return {"metrics": {}, "equity_curve": [], "trades": [], "entries_exits": []}
"""


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


def test_run_real_backtest_applies_corporate_action_adjustment_via_close_curve():
    """REL-072 exit criterion: `run_real_backtest()` -- the function every real backtest in this
    app actually goes through -- previously never applied split/bonus adjustment at all (a real,
    confirmed gap; the adjustment pipeline above was real and tested but had zero real callers on
    this path). Proves the fix the same way the test above proves the underlying mechanism: a
    real, clearly-labeled TEST corporate action, real RELIANCE price data, a real measurable
    diff."""
    _seed_test_action()
    try:
        date_from = _EX_DATE - timedelta(days=30)
        date_to = _EX_DATE + timedelta(days=5)

        adjusted_outcome = run_real_backtest(
            _MINIMAL_STRATEGY_CODE,
            universe=[_SYMBOL],
            date_from=date_from,
            date_to=date_to,
            adjust_for_corporate_actions=True,
        )
        assert adjusted_outcome.passed, adjusted_outcome.error
        assert adjusted_outcome.data_adjusted is True

        unadjusted_outcome = run_real_backtest(
            _MINIMAL_STRATEGY_CODE,
            universe=[_SYMBOL],
            date_from=date_from,
            date_to=date_to,
            adjust_for_corporate_actions=False,
        )
        assert unadjusted_outcome.passed, unadjusted_outcome.error
        assert unadjusted_outcome.data_adjusted is False

        ex_date_iso = _EX_DATE.isoformat()
        adjusted_pre = next(p for p in adjusted_outcome.close_curve if p.date < ex_date_iso)
        unadjusted_pre = next(p for p in unadjusted_outcome.close_curve if p.date < ex_date_iso)
        assert adjusted_pre.date == unadjusted_pre.date
        # The real, measurable diff: exactly halved (the same 1:2 test split the mechanism test
        # above seeds), proving run_real_backtest's new Polars<->pandas round-trip actually
        # applies the real adjustment math, not just threads the flag through unused.
        assert adjusted_pre.close == unadjusted_pre.close / 2

        adjusted_post = next(p for p in adjusted_outcome.close_curve if p.date >= ex_date_iso)
        unadjusted_post = next(p for p in unadjusted_outcome.close_curve if p.date >= ex_date_iso)
        assert adjusted_post.close == unadjusted_post.close
    finally:
        _cleanup()
