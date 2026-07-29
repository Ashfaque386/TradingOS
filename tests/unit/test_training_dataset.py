from datetime import date, timedelta

import polars as pl
import pytest

from src.ml.training.baselines import buy_and_hold_return, momentum_baseline_accuracy
from src.ml.training.dataset import build_labels, chronological_split


def _frame(closes: list[float]) -> pl.DataFrame:
    start = date(2024, 1, 1)
    return pl.DataFrame(
        {
            "date": [start + timedelta(days=i) for i in range(len(closes))],
            "close": closes,
        }
    )


def test_chronological_split_never_straddles_dates_out_of_order() -> None:
    df = _frame([float(i) for i in range(100)])
    train, valid, test = chronological_split(df, train_frac=0.7, valid_frac=0.15)

    assert train["date"].max() < valid["date"].min()
    assert valid["date"].max() < test["date"].min()
    assert train.height + valid.height + test.height == df.height


def test_chronological_split_raises_on_empty_split() -> None:
    df = _frame([1.0, 2.0, 3.0])  # too small for a 3-way split at these fractions
    with pytest.raises(ValueError, match="empty"):
        chronological_split(df, train_frac=0.9, valid_frac=0.09)


def test_chronological_split_rejects_invalid_fractions() -> None:
    df = _frame([float(i) for i in range(10)])
    with pytest.raises(ValueError):
        chronological_split(df, train_frac=0.7, valid_frac=0.5)  # sums to >= 1


def test_build_labels_classification_matches_hand_computed_values() -> None:
    df = _frame([10.0, 12.0, 11.0, 15.0])
    labeled = build_labels(df, "classification")

    # Last row dropped (no next-day close to compare against).
    assert labeled.height == 3
    assert labeled["label"].to_list() == [1, 0, 1]  # 10->12 up, 12->11 down, 11->15 up


def test_build_labels_regression_matches_hand_computed_values() -> None:
    df = _frame([100.0, 101.0, 102.0, 103.0, 104.0, 110.0, 90.0])
    labeled = build_labels(df, "regression", horizon=5)

    assert labeled.height == 2  # 7 rows - horizon 5
    expected_0 = (110.0 - 100.0) / 100.0
    expected_1 = (90.0 - 101.0) / 101.0
    assert labeled["label"].to_list() == pytest.approx([expected_0, expected_1])


def test_build_labels_rejects_unknown_task() -> None:
    df = _frame([10.0, 11.0])
    with pytest.raises(ValueError, match="unknown task"):
        build_labels(df, "not-a-real-task")  # type: ignore[arg-type]


def test_buy_and_hold_return_matches_hand_computation() -> None:
    df = _frame([100.0, 110.0, 90.0, 120.0])
    assert buy_and_hold_return(df) == pytest.approx((120.0 - 100.0) / 100.0)


def test_momentum_baseline_accuracy_is_between_0_and_1() -> None:
    df = _frame([10.0 + (i % 7) for i in range(40)])
    accuracy = momentum_baseline_accuracy(df, lookback=5)
    assert 0.0 <= accuracy <= 1.0


def test_momentum_baseline_accuracy_raises_on_too_short_input() -> None:
    df = _frame([10.0, 11.0])
    with pytest.raises(ValueError, match="too short"):
        momentum_baseline_accuracy(df, lookback=5)
