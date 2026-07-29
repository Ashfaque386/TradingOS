from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest

from src.ml.features.store import (
    build_feature_frame,
    compute_training_data_hash,
    read_feature_store,
    rolling_vwap,
    write_feature_store,
)


def _ohlcv(closes: list[float], start: date = date(2024, 1, 1)) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": ["TEST"] * len(closes),
            "date": [start + timedelta(days=i) for i in range(len(closes))],
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [1000 + i for i in range(len(closes))],
        }
    )


def _write_raw_lake(root: Path, symbol: str, df: pl.DataFrame) -> None:
    # Mirrors ParquetLakeWriter's partition layout closely enough for DataLake's glob read
    # (<root>/*/*/<symbol>.parquet) -- a single partition file is sufficient for these tests.
    partition = root / "2024" / "01"
    partition.mkdir(parents=True, exist_ok=True)
    df.write_parquet(partition / f"{symbol}.parquet")


def test_rolling_vwap_is_between_low_and_high_range() -> None:
    df = _ohlcv([10 + i for i in range(30)])
    result = rolling_vwap(df, window=20)
    non_null = [v for v in result.to_list() if v is not None]
    assert non_null
    assert all(v > 0 for v in non_null)


def test_build_feature_frame_raises_on_duplicate_dates(tmp_path: Path) -> None:
    df = _ohlcv([10.0 + i for i in range(30)])
    # Introduce a real duplicate (symbol, date) row with a materially different close, mirroring
    # HDFCBANK's real corrupted data.
    dup_row = df.head(1).with_columns(pl.lit(999.0).alias("close"))
    corrupted = pl.concat([df, dup_row])
    _write_raw_lake(tmp_path, "TEST", corrupted)

    with pytest.raises(ValueError, match="duplicate-date"):
        build_feature_frame("TEST", date(2024, 1, 1), date(2024, 1, 30), lake_root=tmp_path)


def test_build_feature_frame_drops_warmup_rows_and_computes_features(tmp_path: Path) -> None:
    df = _ohlcv([10 + i for i in range(40)])
    _write_raw_lake(tmp_path, "TEST", df)

    result = build_feature_frame("TEST", date(2024, 1, 1), date(2024, 2, 20), lake_root=tmp_path)

    assert result.height > 0
    assert result.height < df.height  # warm-up rows dropped
    for col in ["sma_20", "macd_line", "macd_signal", "macd_hist", "vwap_20"]:
        assert col in result.columns
        assert result[col].null_count() == 0


def test_compute_training_data_hash_is_deterministic_and_sensitive() -> None:
    df1 = _ohlcv([10, 20, 30])
    df2 = _ohlcv([10, 20, 30])
    df3 = _ohlcv([10, 20, 31])

    assert compute_training_data_hash(df1) == compute_training_data_hash(df2)
    assert compute_training_data_hash(df1) != compute_training_data_hash(df3)


def test_write_then_read_feature_store_round_trips(tmp_path: Path) -> None:
    df = _ohlcv([10 + i for i in range(25)])
    write_feature_store(df, tmp_path, "TEST", version="fs_test")

    result = read_feature_store("TEST", tmp_path, version="fs_test")

    assert result.height == df.height
    assert set(df.columns) == set(result.columns)


def test_read_feature_store_returns_empty_frame_when_nothing_written(tmp_path: Path) -> None:
    result = read_feature_store("NOPE", tmp_path, version="fs_test")
    assert result.height == 0
