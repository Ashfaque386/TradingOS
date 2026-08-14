"""REL-053: bridges the LLM-generated sandboxed strategy code onto `optuna_sweep.py`'s
`StrategyFactory` contract (`dict[str, float] -> StrategyFn`).

Fundamentally different from `walk_forward_adapter.py`'s own adapter: WFO replays ONE already-
captured real signal series across rolling windows (cheap, no re-execution). Optuna needs a
DIFFERENT signal series per trial, since each trial's parameters genuinely change the generated
code's behavior (per PMPT-004 v4's `config.get("params", {})` contract) -- there is no way to
avoid re-running the real sandboxed backtest once per trial here, unlike WFO's case. This is a
real, measurable per-trial cost (see backtest_runner.py's own docstring: ~9-29s cold / ~0.06s
warm per call) `optimization_node` must budget `n_trials` against.
"""

from datetime import date
from typing import Any

import pandas as pd

from src.engine.optimization.optuna_sweep import StrategyFactory
from src.engine.optimization.walk_forward import StrategyFn
from src.engine.sandbox.backtest_runner import run_real_backtest


def sandboxed_code_to_strategy_factory(
    code: str,
    *,
    universe: list[str],
    date_from: date,
    date_to: date,
    base_config: dict[str, Any] | None = None,
) -> StrategyFactory:
    """Returns a `StrategyFactory`: given a trial's `params`, re-runs the real sandboxed backtest
    with `config["params"] = params` and extracts a real `StrategyFn` from its real
    `entries_exits` output -- never a fabricated or reused-from-elsewhere signal series."""

    def factory(params: dict[str, float]) -> StrategyFn:
        def strategy_fn(close: pd.Series) -> tuple[pd.Series, pd.Series]:
            config = {**(base_config or {}), "params": params}
            outcome = run_real_backtest(
                code, universe=universe, date_from=date_from, date_to=date_to, config=config
            )
            if not outcome.passed:
                # A parameter combination the generated code can't handle -- no entries/exits,
                # matching optuna_sweep.py's own -inf-for-a-dead-region convention (a trial that
                # produces zero closed trades already scores -inf there), not a crash here.
                empty = pd.Series(False, index=close.index)
                return empty, empty
            dates = pd.to_datetime([p.date for p in outcome.entries_exits])
            entries = pd.Series([p.entry for p in outcome.entries_exits], index=dates).reindex(
                close.index, fill_value=False
            )
            exits = pd.Series([p.exit for p in outcome.entries_exits], index=dates).reindex(
                close.index, fill_value=False
            )
            return entries, exits

        return strategy_fn

    return factory
