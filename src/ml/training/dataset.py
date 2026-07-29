"""REL-008 E8.2: chronological train/valid/test splitting and label construction.

Phase_5_Machine_Learning_Architecture.md §2's training workflow is explicit: "Time-Series Split:
Strict chronological splitting ... No K-Fold cross-validation is allowed to prevent look-ahead
bias." The design doc's own example (Train 2018-2022 / Valid 2023 / Test 2024) assumes 5 years of
data; this codebase's real ingested data lake covers ~1 year (2023-07-21 to 2024-07-19, confirmed
live), so splits are expressed as fractions of whatever real date range is passed in, not fixed
calendar years -- a deliberate, documented dev-environment scope reduction, not a silent shortcut.
"""

from typing import Literal

import polars as pl


def chronological_split(
    df: pl.DataFrame, train_frac: float = 0.70, valid_frac: float = 0.15
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """`df` must already be sorted by date (build_feature_frame() guarantees this). Splits by row
    position, not calendar date arithmetic, so it works identically regardless of how many real
    trading days exist in the input. Raises ValueError if any resulting split would be empty --
    silently training on a 0-row split is worse than a loud, early failure."""
    if not 0 < train_frac < 1 or not 0 < valid_frac < 1 or train_frac + valid_frac >= 1:
        raise ValueError(
            f"train_frac ({train_frac}) and valid_frac ({valid_frac}) must each be in (0, 1) "
            "and sum to less than 1 (the remainder becomes the test split)"
        )

    n = df.height
    train_end = int(n * train_frac)
    valid_end = train_end + int(n * valid_frac)

    train = df.slice(0, train_end)
    valid = df.slice(train_end, valid_end - train_end)
    test = df.slice(valid_end, n - valid_end)

    for name, split in (("train", train), ("valid", valid), ("test", test)):
        if split.height == 0:
            raise ValueError(
                f"the {name!r} split is empty ({n} total rows, train_frac={train_frac}, "
                f"valid_frac={valid_frac}) -- widen the input date range or adjust the fractions"
            )

    return train, valid, test


def build_labels(
    df: pl.DataFrame, task: Literal["classification", "regression"], *, horizon: int = 5
) -> pl.DataFrame:
    """Appends a `label` column and drops the trailing rows where the forward-looking label isn't
    defined (there's no future close to compare against). Matches Phase_5 §2's own named examples
    exactly: classification = "will [it] close green tomorrow?" (next-day direction);
    regression = "predict next 5-minute return" -- reinterpreted here as next-`horizon`-DAY
    forward return, since this codebase's real data is daily EOD bars, not intraday ticks."""
    if task == "classification":
        labeled = df.with_columns(
            (pl.col("close").shift(-1) > pl.col("close")).cast(pl.Int8).alias("label")
        )
    elif task == "regression":
        labeled = df.with_columns(
            ((pl.col("close").shift(-horizon) - pl.col("close")) / pl.col("close")).alias("label")
        )
    else:
        raise ValueError(f"unknown task {task!r}")

    return labeled.filter(pl.col("label").is_not_null())
