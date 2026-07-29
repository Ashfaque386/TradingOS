"""REL-008 E8.2: real, simple baselines Phase_5 §2 requires every candidate model be compared
against ("Evaluation: Compare against a Buy & Hold benchmark and a momentum baseline.")."""

import polars as pl


def buy_and_hold_return(df: pl.DataFrame) -> float:
    """Total return of simply holding from the first close in `df` to the last."""
    first_close = float(df["close"][0])
    last_close = float(df["close"][-1])
    return (last_close - first_close) / first_close


def momentum_baseline_accuracy(df: pl.DataFrame, lookback: int = 5) -> float:
    """A naive momentum rule: predict tomorrow's direction as "same sign as the return over the
    last `lookback` days." Accuracy against the real next-day direction, over every row where
    both the lookback return and the next-day outcome are defined."""
    momentum = (pl.col("close") - pl.col("close").shift(lookback)) / pl.col("close").shift(lookback)
    next_day_up = pl.col("close").shift(-1) > pl.col("close")
    predicted_up = momentum > 0

    evaluated = df.with_columns(
        momentum.alias("_momentum"),
        next_day_up.alias("_next_day_up"),
        predicted_up.alias("_predicted_up"),
    ).filter(pl.col("_momentum").is_not_null() & pl.col("_next_day_up").is_not_null())

    if evaluated.height == 0:
        raise ValueError(
            f"no rows have both a defined {lookback}-day lookback and a next-day outcome -- "
            "input frame is too short"
        )

    correct = int((evaluated["_predicted_up"] == evaluated["_next_day_up"]).sum())
    return correct / evaluated.height
