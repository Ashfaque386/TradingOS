"""YahooFinanceProvider + YahooSymbolMapper unit tests (REL-070). `yf.Ticker` is monkeypatched
at the module level (matching tests/unit/test_market_pulse.py's own monkeypatch convention) --
no real network call.
"""

from datetime import date

import pandas as pd
import pytest

from src.data.providers.base import ProviderEmptyDataError, ProviderNetworkError
from src.data.providers.yahoo_finance import YahooFinanceProvider, YahooSymbolMapper

_DAY = date(2026, 8, 1)


def _history(rows: list[tuple[str, float, float, float, float, int]]) -> pd.DataFrame:
    index = pd.to_datetime([r[0] for r in rows]).tz_localize("Asia/Kolkata")
    return pd.DataFrame(
        {
            "Open": [r[1] for r in rows],
            "High": [r[2] for r in rows],
            "Low": [r[3] for r in rows],
            "Close": [r[4] for r in rows],
            "Volume": [r[5] for r in rows],
        },
        index=index,
    )


class _FakeTicker:
    def __init__(
        self, frame: pd.DataFrame | None = None, *, raises: Exception | None = None
    ) -> None:
        self._frame = frame if frame is not None else pd.DataFrame()
        self._raises = raises

    def history(self, **kwargs: object) -> pd.DataFrame:
        if self._raises is not None:
            raise self._raises
        return self._frame


# --- YahooSymbolMapper ---------------------------------------------------------------------


def test_nse_equity_gets_ns_suffix():
    assert YahooSymbolMapper.to_yahoo_symbol("RELIANCE") == "RELIANCE.NS"


def test_bse_equity_gets_bo_suffix():
    assert YahooSymbolMapper.to_yahoo_symbol("RELIANCE", exchange="BSE") == "RELIANCE.BO"


def test_index_ticker_is_never_suffixed():
    assert YahooSymbolMapper.to_yahoo_symbol("^NSEI") == "^NSEI"


def test_already_suffixed_symbol_is_passed_through():
    assert YahooSymbolMapper.to_yahoo_symbol("RELIANCE.NS") == "RELIANCE.NS"


def test_unknown_exchange_returns_none():
    assert YahooSymbolMapper.to_yahoo_symbol("RELIANCE", exchange="MCX") is None


# --- YahooFinanceProvider -------------------------------------------------------------------


def test_get_historical_data_returns_real_normalized_candles(monkeypatch):
    frame = _history([("2026-08-01", 100.0, 105.0, 99.0, 103.0, 15000)])
    monkeypatch.setattr(
        "src.data.providers.yahoo_finance.yf.Ticker", lambda symbol: _FakeTicker(frame)
    )

    provider = YahooFinanceProvider()
    candles = provider.get_historical_data(
        instrument_key="RELIANCE", symbol="RELIANCE", start=_DAY, end=_DAY, timeframe="1d"
    )

    assert len(candles) == 1
    assert candles[0].close == 103.0
    assert candles[0].provider == "yfinance"
    assert candles[0].timestamp.tzinfo is not None


def test_empty_history_raises_empty_data_error(monkeypatch):
    monkeypatch.setattr(
        "src.data.providers.yahoo_finance.yf.Ticker", lambda symbol: _FakeTicker(pd.DataFrame())
    )
    provider = YahooFinanceProvider()
    with pytest.raises(ProviderEmptyDataError):
        provider.get_historical_data(
            instrument_key="RELIANCE", symbol="RELIANCE", start=_DAY, end=_DAY, timeframe="1d"
        )


def test_network_failure_raises_network_error(monkeypatch):
    monkeypatch.setattr(
        "src.data.providers.yahoo_finance.yf.Ticker",
        lambda symbol: _FakeTicker(raises=RuntimeError("real network failure for test")),
    )
    provider = YahooFinanceProvider()
    with pytest.raises(ProviderNetworkError):
        provider.get_historical_data(
            instrument_key="RELIANCE", symbol="RELIANCE", start=_DAY, end=_DAY, timeframe="1d"
        )


def test_health_check_true_when_ticker_returns_data(monkeypatch):
    frame = _history([("2026-08-01", 100.0, 105.0, 99.0, 103.0, 15000)])
    monkeypatch.setattr(
        "src.data.providers.yahoo_finance.yf.Ticker", lambda symbol: _FakeTicker(frame)
    )
    assert YahooFinanceProvider().health_check() is True


def test_health_check_false_on_failure(monkeypatch):
    monkeypatch.setattr(
        "src.data.providers.yahoo_finance.yf.Ticker",
        lambda symbol: _FakeTicker(raises=RuntimeError("down")),
    )
    assert YahooFinanceProvider().health_check() is False
