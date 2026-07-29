"""REL-008 E8.1: Feature Store against the real ingested data lake (real RELIANCE OHLCV, and a
real assertion that HDFCBANK's genuine duplicate-date rows are caught, not silently trained on)."""

from datetime import date
from pathlib import Path

import pytest

from src.core.config import get_settings
from src.ml.features.store import (
    build_feature_frame,
    read_feature_store,
    write_feature_store,
)


def _ohlcv_root() -> Path:
    return get_settings().data_lake_root / "ohlcv_daily"


def test_build_feature_frame_against_real_reliance_data() -> None:
    df = build_feature_frame(
        "RELIANCE",
        date(2023, 7, 21),
        date(2024, 7, 19),
        lake_root=_ohlcv_root(),
    )

    assert df.height > 0
    for col in ["sma_20", "rsi_14", "macd_line", "vwap_20"]:
        assert col in df.columns
        assert df[col].null_count() == 0


def test_build_feature_frame_raises_on_hdfcbank_real_duplicate_dates() -> None:
    with pytest.raises(ValueError, match="duplicate-date"):
        build_feature_frame(
            "HDFCBANK",
            date(2023, 7, 21),
            date(2024, 7, 19),
            lake_root=_ohlcv_root(),
        )


def test_write_then_read_feature_store_round_trips_against_real_data(tmp_path: Path) -> None:
    df = build_feature_frame(
        "RELIANCE",
        date(2023, 7, 21),
        date(2024, 7, 19),
        lake_root=_ohlcv_root(),
    )

    write_feature_store(df, tmp_path, "RELIANCE", version="fs_test")
    result = read_feature_store("RELIANCE", tmp_path, version="fs_test")

    assert result.height == df.height
    assert set(df.columns) == set(result.columns)
