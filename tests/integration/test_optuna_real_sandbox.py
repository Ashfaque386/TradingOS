"""REL-053: the real Optuna sweep, end-to-end -- real sandbox execution (no mocking), against
real TCS data (the same year used by test_real_backtest_runner.py). A tiny, hand-written
parameterized strategy (not LLM-generated) so this test is deterministic and independent of any
LLM call; the point is to prove the real pipeline (sandbox execution per trial -> real
entries/exits extraction -> Optuna trial loop -> a real, non-fabricated best value), not to prove
strategy quality.

Deliberately small n_trials (3): each trial re-executes the real sandboxed backtest (see
optuna_strategy_adapter.py's own docstring for why this can't be avoided), and a single real call
was independently timed at ~42s in this environment -- the warm sandbox pool (REL-032) keeps
subsequent trials fast within the same sweep, but this test still budgets for a slow first trial.
"""

from datetime import date

import pandas as pd

from src.engine.optimization.optuna_strategy_adapter import sandboxed_code_to_strategy_factory
from src.engine.optimization.optuna_sweep import run_optuna_sweep

_PARAMETERIZED_STRATEGY_CODE = """
import polars as pl
import vectorbt as vbt


def run_backtest(data: pl.DataFrame, config: dict) -> dict:
    params = config.get("params", {})
    window = int(params.get("window", 10))
    close = data["close"].to_pandas()
    close.index = data["date"].to_pandas()
    sma = close.rolling(window).mean()
    entries = (close > sma) & (close.shift(1) <= sma.shift(1))
    exits = (close < sma) & (close.shift(1) >= sma.shift(1))
    pf = vbt.Portfolio.from_signals(
        close, entries, exits, init_cash=config.get("init_cash", 100000), freq="1D"
    )

    def clean(x):
        try:
            x = float(x)
            return x if x == x and abs(x) != float("inf") else None
        except Exception:
            return None

    metrics = {
        "sharpe_ratio": clean(pf.sharpe_ratio()),
        "sortino_ratio": clean(pf.sortino_ratio()),
        "calmar_ratio": clean(pf.calmar_ratio()),
        "max_drawdown": clean(pf.max_drawdown()),
        "cagr": clean(pf.annualized_return()),
        "win_rate": clean(pf.trades.win_rate()),
        "profit_factor": clean(pf.trades.profit_factor()),
        "expectancy": clean(pf.trades.expectancy()),
        "total_trades": int(pf.trades.count()),
    }
    equity_curve = [{"date": str(d.date()), "equity": float(v)} for d, v in pf.value().items()]
    entries_exits = [
        {"date": str(d.date()), "entry": bool(en), "exit": bool(ex)}
        for d, en, ex in zip(entries.index, entries.values, exits.values, strict=True)
    ]
    return {
        "metrics": metrics,
        "equity_curve": equity_curve,
        "trades": [],
        "entries_exits": entries_exits,
    }
"""

_DATE_FROM = date(2023, 7, 1)
_DATE_TO = date(2024, 7, 1)


def _real_tcs_close() -> pd.Series:
    from src.core.config import get_settings
    from src.data.datalake.query import DataLake

    lake = DataLake(get_settings().data_lake_root / "ohlcv_daily")
    df = lake.read_symbol("TCS", start=_DATE_FROM, end=_DATE_TO).sort("date")
    return pd.Series(df["close"].to_list(), index=pd.to_datetime(df["date"].to_list()))


def test_optuna_sweep_runs_end_to_end_against_the_real_sandbox():
    close = _real_tcs_close()
    factory = sandboxed_code_to_strategy_factory(
        _PARAMETERIZED_STRATEGY_CODE,
        universe=["TCS"],
        date_from=_DATE_FROM,
        date_to=_DATE_TO,
    )

    result = run_optuna_sweep(
        close,
        {"window": ("int", 5, 60)},
        factory,
        n_trials=3,
        seed=42,
    )

    assert len(result.trials) == 3
    assert result.best_value != float("-inf")
    assert 5 <= result.best_params["window"] <= 60
