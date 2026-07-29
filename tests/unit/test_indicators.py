from datetime import date, timedelta

import polars as pl
import pytest

from src.data.features.indicators import (
    atr,
    bollinger_bands,
    ema,
    macd,
    rsi,
    sma,
    with_indicators,
)


def _ohlcv(closes: list[float]) -> pl.DataFrame:
    start = date(2024, 1, 1)
    return pl.DataFrame(
        {
            "date": [start + timedelta(days=i) for i in range(len(closes))],
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [1000] * len(closes),
        }
    )


def test_sma_matches_manual_average():
    df = _ohlcv([10, 20, 30, 40, 50])
    result = sma(df, window=3)
    assert result[2] == pytest.approx((10 + 20 + 30) / 3)
    assert result[4] == pytest.approx((30 + 40 + 50) / 3)


def test_ema_is_defined_for_every_row():
    df = _ohlcv([10, 20, 30, 40, 50])
    result = ema(df, span=3)
    assert result.null_count() == 0
    assert result.len() == 5


def test_rsi_is_100_when_strictly_increasing():
    df = _ohlcv([10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25])
    result = rsi(df, window=14)
    assert result[-1] == pytest.approx(100.0, abs=0.01)


def test_rsi_is_0_when_strictly_decreasing():
    df = _ohlcv([25, 24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10])
    result = rsi(df, window=14)
    assert result[-1] == pytest.approx(0.0, abs=0.01)


def test_atr_is_nonnegative():
    df = _ohlcv([10, 12, 9, 15, 11, 20, 8])
    result = atr(df, window=3)
    assert all(v is None or v >= 0 for v in result.to_list())


def test_bollinger_bands_upper_above_lower():
    df = _ohlcv(
        [10, 12, 11, 13, 15, 14, 16, 18, 17, 19, 20, 22, 21, 23, 25, 24, 26, 28, 27, 29, 30]
    )
    upper, mid, lower = bollinger_bands(df, window=20)
    last_upper, last_mid, last_lower = upper[-1], mid[-1], lower[-1]
    assert last_upper >= last_mid >= last_lower


def test_macd_line_is_positive_when_strictly_increasing():
    df = _ohlcv([10 + i for i in range(60)])
    macd_line, signal_line, histogram = macd(df)
    assert macd_line[-1] > 0
    assert histogram.len() == df.height
    assert signal_line.len() == df.height


def test_macd_line_is_negative_when_strictly_decreasing():
    df = _ohlcv([100 - i for i in range(60)])
    macd_line, _signal_line, _histogram = macd(df)
    assert macd_line[-1] < 0


def test_with_indicators_appends_all_expected_columns():
    df = _ohlcv([10 + i for i in range(25)])
    result = with_indicators(df)
    for column in ["sma_20", "ema_20", "rsi_14", "atr_14", "bb_upper", "bb_mid", "bb_lower"]:
        assert column in result.columns
    assert result.height == df.height
