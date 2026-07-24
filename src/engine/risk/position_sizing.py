"""Volatility-adjusted position sizing (Phase 3 Epic E3.4), per Phase_6_Trading_Engine_Design.md
§4 -- part of the **hardcoded** Risk & Portfolio Engine ("the AI cannot modify these rules"):

  "Position Sizing: Volatility-adjusted sizing. A highly volatile stock gets a smaller capital
  allocation than a stable blue-chip, ensuring equal risk contribution across the portfolio."

This is the standard inverse-volatility ("risk parity") weighting scheme: each symbol's target
capital weight is proportional to 1/volatility, normalized to sum to 1, so that a symbol twice
as volatile as another gets half the capital allocation -- both then contribute the same amount
of portfolio risk (weight * volatility is equal across all symbols).
"""

import math
from dataclasses import dataclass

import pandas as pd


def compute_volatility(returns: pd.Series, *, window: int | None = None) -> float:
    """Standard deviation of a return series, optionally restricted to the trailing `window`
    observations (most-recent volatility rather than the whole history)."""
    series = returns.tail(window) if window is not None else returns
    return float(series.std())


@dataclass(frozen=True)
class PositionSizeResult:
    weight: float
    capital_allocation: float
    shares: int


def compute_inverse_volatility_weights(volatilities: dict[str, float]) -> dict[str, float]:
    """Normalizes `{symbol: volatility}` into capital weights proportional to 1/volatility,
    summing to 1.0. A symbol with zero (or non-finite) volatility is excluded entirely rather
    than assigned an undefined infinite weight -- a strategy with a perfectly flat return
    series is a data problem, not something to bet the whole portfolio on."""
    inverse_vols = {
        symbol: 1.0 / vol for symbol, vol in volatilities.items() if vol > 0 and math.isfinite(vol)
    }
    total = sum(inverse_vols.values())
    if total == 0:
        return dict.fromkeys(volatilities, 0.0)
    return {symbol: inv_vol / total for symbol, inv_vol in inverse_vols.items()}


def compute_position_sizes(
    returns_by_symbol: dict[str, pd.Series],
    prices: dict[str, float],
    total_capital: float,
    *,
    window: int | None = None,
) -> dict[str, PositionSizeResult]:
    """End-to-end: per-symbol volatility -> inverse-volatility weights -> capital allocation ->
    whole-share position size at each symbol's current `price`."""
    volatilities = {
        symbol: compute_volatility(returns, window=window)
        for symbol, returns in returns_by_symbol.items()
    }
    weights = compute_inverse_volatility_weights(volatilities)

    results = {}
    for symbol, weight in weights.items():
        capital_allocation = weight * total_capital
        shares = int(capital_allocation // prices[symbol]) if prices[symbol] > 0 else 0
        results[symbol] = PositionSizeResult(
            weight=weight, capital_allocation=capital_allocation, shares=shares
        )
    return results
