"""Real split/bonus back-adjustment for backtest OHLCV data (REL-010 E10.7).

Prior to this module, src/engine/backtest/data_feed.py read raw DataLake.read_symbol() output
with zero corporate-action adjustment -- a real correctness gap: a stock split/bonus produces an
artificial price discontinuity on its ex-date that a backtest would otherwise misread as a real
100%+ single-day move (or, for the strategy's returns math, an equally fake single-day loss).

Dividends are recorded in `corporate_actions` (src/models/corporate_action.py) but deliberately
NOT price-adjusted here: a proper dividend adjustment requires a total-return series (reinvesting
the dividend back into the price), which no part of this codebase computes today. Applying only
a naive ex-dividend price drop without the offsetting reinvestment would make total-return
comparisons WORSE, not better -- so this is an honest, stated scope limit, not an oversight.
"""

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.corporate_action import CorporateAction

_SPLIT_BONUS_TYPES = ("SPLIT", "BONUS")


def load_corporate_actions(session: Session, symbol: str) -> list[CorporateAction]:
    return list(
        session.scalars(
            select(CorporateAction)
            .where(CorporateAction.symbol == symbol)
            .order_by(CorporateAction.ex_date)
        )
    )


def adjust_ohlcv_for_corporate_actions(
    df: pd.DataFrame, actions: list[CorporateAction]
) -> pd.DataFrame:
    """`df` is indexed by date with `open`/`high`/`low`/`close` columns (volume is
    deliberately NOT adjusted -- share count, not traded value, changes on a split/bonus).
    Back-adjustment walks every SPLIT/BONUS action's `ex_date` newest-to-oldest, multiplying
    every row strictly BEFORE that date by (ratio_numerator/ratio_denominator) -- see
    src/models/corporate_action.py's own docstring for why that's the correct direction
    (more post-action shares means a proportionally lower price)."""
    if df.empty:
        return df

    adjusted = df.copy()
    price_columns = [c for c in ("open", "high", "low", "close") if c in adjusted.columns]

    relevant_actions = sorted(
        (
            a
            for a in actions
            if a.action_type in _SPLIT_BONUS_TYPES
            and a.ratio_numerator is not None
            and a.ratio_denominator
        ),
        key=lambda a: a.ex_date,
        reverse=True,
    )
    for action in relevant_actions:
        # The generator filter above already guarantees both are non-None -- mypy's narrowing
        # doesn't survive the `sorted(...)` round-trip, so re-assert it here explicitly.
        assert action.ratio_numerator is not None
        assert action.ratio_denominator is not None
        factor = float(action.ratio_numerator) / float(action.ratio_denominator)
        # `pd.Timestamp(...)`, not a bare `date`, for the comparison -- avoids relying on
        # implicit coercion between a DatetimeIndex and a plain `datetime.date` scalar.
        mask = adjusted.index < pd.Timestamp(action.ex_date)
        adjusted.loc[mask, price_columns] = adjusted.loc[mask, price_columns] * factor

    return adjusted
