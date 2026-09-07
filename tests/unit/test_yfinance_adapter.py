"""YFinanceAdapter unit tests. `yf.Ticker(...).history()` is mocked directly (a third-party
library with its own internal HTTP session, not something `httpx.MockTransport` can intercept),
matching this file's own need rather than test_bhavcopy.py's httpx-level mocking.

Found during the "Genuinely Open items" research pass: this adapter (the CLI-only, direct
MarketDataManager-bypassing debug path, per its own module docstring) had zero dedicated tests.
"""

from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import polars as pl

from src.data.ingest.yfinance_adapter import YFinanceAdapter

_START = date(2026, 8, 3)
_END = date(2026, 8, 4)


def _real_shaped_history(close: float) -> pd.DataFrame:
    """Matches yfinance's own real `.history()` return shape: a DatetimeIndex named "Date" and
    Open/High/Low/Close/Volume columns (plus Dividends/Stock Splits, ignored by the adapter)."""
    return pd.DataFrame(
        {
            "Open": [close - 10],
            "High": [close + 5],
            "Low": [close - 15],
            "Close": [close],
            "Volume": [1_000_000],
        },
        index=pd.DatetimeIndex([pd.Timestamp(_START)], name="Date"),
    )


def _empty_history() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["Open", "High", "Low", "Close", "Volume"],
        index=pd.DatetimeIndex([], name="Date"),
    )


def test_fetch_skips_a_symbol_the_mapper_cannot_resolve_but_keeps_the_rest():
    """YahooSymbolMapper.to_yahoo_symbol returns None for an exchange it has no real convention
    for (yfinance_adapter.py:38-40) -- confirmed the adapter's own handling of that return value
    directly, since the adapter's one real call site always passes NSE's default exchange today
    and so never reaches this branch on its own; the branch itself must still degrade correctly
    if that ever changes."""
    with (
        patch(
            "src.data.ingest.yfinance_adapter.YahooSymbolMapper.to_yahoo_symbol",
            side_effect=lambda symbol: None if symbol == "UNMAPPABLE" else f"{symbol}.NS",
        ),
        patch("src.data.ingest.yfinance_adapter.yf.Ticker") as mock_ticker,
    ):
        mock_ticker.return_value.history.return_value = _real_shaped_history(2940.0)

        result = YFinanceAdapter().fetch(["UNMAPPABLE", "RELIANCE"], _START, _END)

    assert result["symbol"].to_list() == ["RELIANCE"]
    mock_ticker.assert_called_once_with("RELIANCE.NS")


def test_fetch_degrades_gracefully_when_one_symbols_request_raises():
    """yfinance raises assorted network/library errors for one symbol while another succeeds --
    fetch() must still return the other symbol's real data, not lose the whole run or raise."""

    def ticker_side_effect(yahoo_symbol: str) -> MagicMock:
        mock = MagicMock()
        if yahoo_symbol == "BADTICKER.NS":
            mock.history.side_effect = ConnectionError("real network failure")
        else:
            mock.history.return_value = _real_shaped_history(2940.0)
        return mock

    with patch("src.data.ingest.yfinance_adapter.yf.Ticker", side_effect=ticker_side_effect):
        result = YFinanceAdapter().fetch(["BADTICKER", "RELIANCE"], _START, _END)

    assert result["symbol"].to_list() == ["RELIANCE"]
    assert result["close"].to_list() == [2940.0]


def test_fetch_skips_a_symbol_with_no_real_trading_history_in_range():
    with patch("src.data.ingest.yfinance_adapter.yf.Ticker") as mock_ticker:
        mock_ticker.return_value.history.return_value = _empty_history()

        result = YFinanceAdapter().fetch(["RELIANCE"], _START, _END)

    assert isinstance(result, pl.DataFrame)
    assert result.height == 0


def test_fetch_returns_an_empty_typed_frame_when_every_symbol_fails():
    """The real degradation floor: nothing succeeds -- still an empty DataFrame with the right
    schema, not a crash or a None."""
    with patch("src.data.ingest.yfinance_adapter.yf.Ticker") as mock_ticker:
        mock_ticker.return_value.history.return_value = _empty_history()

        result = YFinanceAdapter().fetch(["RELIANCE", "TCS"], _START, _END)

    assert isinstance(result, pl.DataFrame)
    assert result.height == 0
    assert set(result.columns) == {"symbol", "date", "open", "high", "low", "close", "volume"}
