"""Polars-based technical indicators over a single-symbol OHLCV frame
(columns: date, open, high, low, close, volume)."""

import polars as pl


def sma(df: pl.DataFrame, window: int, column: str = "close") -> pl.Series:
    return df[column].rolling_mean(window_size=window)


def ema(df: pl.DataFrame, span: int, column: str = "close") -> pl.Series:
    return df[column].ewm_mean(span=span, adjust=False)


def rsi(df: pl.DataFrame, window: int = 14, column: str = "close") -> pl.Series:
    delta = df[column].diff()
    gain = delta.clip(lower_bound=0)
    loss = (-delta).clip(lower_bound=0)
    avg_gain = gain.ewm_mean(alpha=1 / window, adjust=False)
    avg_loss = loss.ewm_mean(alpha=1 / window, adjust=False)
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def atr(df: pl.DataFrame, window: int = 14) -> pl.Series:
    prev_close = df["close"].shift(1)
    tr_components = pl.DataFrame(
        {
            "hl": (df["high"] - df["low"]).abs(),
            "hc": (df["high"] - prev_close).abs(),
            "lc": (df["low"] - prev_close).abs(),
        }
    )
    tr = tr_components.select(pl.max_horizontal("hl", "hc", "lc")).to_series()
    return tr.ewm_mean(alpha=1 / window, adjust=False)


def bollinger_bands(
    df: pl.DataFrame, window: int = 20, num_std: float = 2.0, column: str = "close"
) -> tuple[pl.Series, pl.Series, pl.Series]:
    middle = sma(df, window, column)
    std = df[column].rolling_std(window_size=window)
    upper = middle + num_std * std
    lower = middle - num_std * std
    return upper, middle, lower


def with_indicators(df: pl.DataFrame) -> pl.DataFrame:
    """Returns `df` with sma_20, ema_20, rsi_14, atr_14, bb_upper/mid/lower columns appended."""
    bb_upper, bb_mid, bb_lower = bollinger_bands(df)
    return df.with_columns(
        sma(df, 20).alias("sma_20"),
        ema(df, 20).alias("ema_20"),
        rsi(df, 14).alias("rsi_14"),
        atr(df, 14).alias("atr_14"),
        bb_upper.alias("bb_upper"),
        bb_mid.alias("bb_mid"),
        bb_lower.alias("bb_lower"),
    )
