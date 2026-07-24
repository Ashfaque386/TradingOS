"""VectorBT backtesting engine core (Phase 3 Epic E3.2).

Open-source `vectorbt` (not VectorBT Pro -- no license available, per the earlier Phase 1
decision recorded in Phase_14_Master_Development_Roadmap.md). Thin wrapper around
vbt.Portfolio.from_signals(): Indian tax/friction modeling (Epic E3.2 second half) layers on
top via the `fees`/`slippage` parameters, computed per-trade rather than hardcoded here.
"""

import pandas as pd
import vectorbt as vbt

# Real EOD data has weekday-only gaps (no weekend/holiday rows), so pandas infers the index
# frequency as "B" (business day). vectorbt's freq_to_timedelta() then calls
# pd.Timedelta(1, unit="B") to compute annualization factors, but "B" was removed as a valid
# Timedelta unit in this pandas version -- verified empirically while building this engine.
# Passing freq explicitly skips that inference entirely; "D" is correct for daily EOD bars
# regardless of which weekdays are actually present.
DEFAULT_FREQ = "D"


def run_backtest(
    close: pd.Series,
    entries: pd.Series,
    exits: pd.Series,
    *,
    init_cash: float = 100_000.0,
    fees: float | pd.Series = 0.0,
    slippage: float | pd.Series = 0.0,
    freq: str = DEFAULT_FREQ,
) -> vbt.Portfolio:
    """Runs a signal-based backtest. `fees`/`slippage` are fractions of trade value (e.g. 0.001
    = 0.1%) -- pass a per-row Series for path-dependent friction (Indian STT/brokerage/slippage
    modeling, src/engine/backtest/friction.py) or a flat float for a quick simulation."""
    return vbt.Portfolio.from_signals(
        close, entries, exits, init_cash=init_cash, fees=fees, slippage=slippage, freq=freq
    )
