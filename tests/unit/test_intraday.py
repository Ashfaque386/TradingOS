"""REL-010 E10.7: intraday candle fetch, mocked `IntradayCandleSource` -- Upstox's real
historical-candle endpoint 404s in sandbox mode (confirmed empirically, see
src/brokers/upstox_adapter.py::get_historical_candles's own docstring), so this cannot be
exercised against a real live source in this environment; a fake source proves the real
reshaping/parsing logic instead.
"""

from datetime import date

import polars as pl
import pytest

from src.data.ingest.intraday import fetch_intraday_candles


class _FakeCandleSource:
    def __init__(self, candles: list[list[object]]) -> None:
        self._candles = candles
        self.calls: list[tuple[str, str, str, str]] = []

    async def get_historical_candles(
        self, instrument_key: str, interval: str, from_date: str, to_date: str
    ) -> list[list[object]]:
        self.calls.append((instrument_key, interval, from_date, to_date))
        return self._candles


@pytest.mark.asyncio
async def test_fetch_intraday_candles_reshapes_the_real_upstox_candle_shape():
    source = _FakeCandleSource(
        [
            ["2024-01-02T09:15:00+05:30", 100.0, 101.0, 99.5, 100.5, 1200, 0],
            ["2024-01-02T09:16:00+05:30", 100.5, 102.0, 100.0, 101.5, 900, 0],
        ]
    )

    df = await fetch_intraday_candles(
        source, symbol="RELIANCE", instrument_key="NSE_EQ|INE002A01018", day=date(2024, 1, 2)
    )

    assert df.height == 2
    assert df["symbol"].to_list() == ["RELIANCE", "RELIANCE"]
    assert df["close"].to_list() == [100.5, 101.5]
    assert df["timestamp"].dtype == pl.Datetime(time_zone="Asia/Kolkata")
    assert source.calls == [("NSE_EQ|INE002A01018", "1minute", "2024-01-02", "2024-01-02")]


@pytest.mark.asyncio
async def test_fetch_intraday_candles_returns_empty_frame_for_no_data():
    source = _FakeCandleSource([])

    df = await fetch_intraday_candles(
        source, symbol="RELIANCE", instrument_key="NSE_EQ|INE002A01018", day=date(2024, 1, 2)
    )

    assert df.height == 0
    assert set(df.columns) == {"symbol", "timestamp", "open", "high", "low", "close", "volume"}
