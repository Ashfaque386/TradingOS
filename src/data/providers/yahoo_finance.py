"""Yahoo Finance market-data provider (REL-070, Phase 1) -- the real fallback provider
(spec §8/§10). Wraps `yfinance`, the same real library `src/data/ingest/yfinance_adapter.py`
already used; that module now delegates its own `.NS`-suffix symbol mapping to
`YahooSymbolMapper` below instead of duplicating it, so there is exactly one real place this
logic lives.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import structlog
import yfinance as yf

from src.data.providers.base import (
    Candle,
    MarketDataProvider,
    ProviderEmptyDataError,
    ProviderInstrumentNotFoundError,
    ProviderNetworkError,
    ProviderUnsupportedIntervalError,
    Timeframe,
)

logger = structlog.get_logger(__name__)

YAHOO_SYMBOL_UNAVAILABLE = "YAHOO_SYMBOL_UNAVAILABLE"
_IST = ZoneInfo("Asia/Kolkata")


class YahooSymbolMapper:
    """Single source of truth for NSE/BSE symbol -> real Yahoo Finance ticker mapping (spec §8)
    -- `.NS`/`.BO` suffixing never happens anywhere else in this codebase.

    REL-016 E16.2 (GLH-08) finding preserved verbatim from the pre-refactor adapter: index
    tickers (e.g. "^NSEI" for Nifty 50) must NOT get a suffix -- Yahoo has no "^NSEI.NS" ticker,
    confirmed the hard way while ingesting real Nifty 50 data. A symbol already carrying a real
    Yahoo suffix is passed through unchanged (idempotent)."""

    @staticmethod
    def to_yahoo_symbol(symbol: str, *, exchange: str = "NSE") -> str | None:
        """Returns `None` (the caller reports `YAHOO_SYMBOL_UNAVAILABLE`) rather than guessing
        when `exchange` isn't one this mapper has a real, confirmed convention for."""
        if symbol.startswith("^") or symbol.endswith(".NS") or symbol.endswith(".BO"):
            return symbol
        if exchange == "NSE":
            return f"{symbol}.NS"
        if exchange == "BSE":
            return f"{symbol}.BO"
        return None


class YahooFinanceProvider(MarketDataProvider):
    name = "yfinance"

    def get_historical_data(
        self,
        *,
        instrument_key: str,
        symbol: str,
        start: date,
        end: date,
        timeframe: Timeframe,
    ) -> list[Candle]:
        if timeframe != "1d":
            # Yahoo's intraday history is real but only retains ~60 real days and is out of
            # scope for Phase 1, which mirrors the existing EOD-only ingestion pipeline -- never
            # silently degrade a finer-grained request to daily bars.
            raise ProviderUnsupportedIntervalError(
                f"yfinance provider only supports timeframe='1d' in Phase 1 (got {timeframe!r})"
            )

        yahoo_symbol = YahooSymbolMapper.to_yahoo_symbol(symbol)
        if yahoo_symbol is None:
            raise ProviderInstrumentNotFoundError(f"{YAHOO_SYMBOL_UNAVAILABLE}: symbol={symbol!r}")

        try:
            history = yf.Ticker(yahoo_symbol).history(start=start, end=end, interval="1d")
        except Exception as exc:  # yfinance raises assorted network/library errors
            raise ProviderNetworkError(f"yfinance fetch failed for {yahoo_symbol}: {exc}") from exc

        if history.empty:
            raise ProviderEmptyDataError(
                f"yfinance returned no data for {yahoo_symbol} {start}..{end}"
            )

        return [
            Candle(
                timestamp=self._to_ist(ts.to_pydatetime()),
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=int(row["Volume"]),
                open_interest=None,  # yfinance never reports real open interest
                instrument_key=instrument_key,
                symbol=symbol,
                timeframe="1d",
                provider=self.name,
            )
            for ts, row in history.iterrows()
        ]

    def get_latest_data(self, *, instrument_key: str, symbol: str) -> Candle | None:
        yahoo_symbol = YahooSymbolMapper.to_yahoo_symbol(symbol)
        if yahoo_symbol is None:
            return None
        try:
            history = yf.Ticker(yahoo_symbol).history(period="1d")
        except Exception as exc:  # noqa: BLE001 -- a real, expected yfinance/network failure mode
            logger.warning("yfinance_latest_data_failed", symbol=symbol, error=str(exc))
            return None
        if history.empty:
            return None
        ts = history.index[-1]
        row = history.iloc[-1]
        return Candle(
            timestamp=self._to_ist(ts.to_pydatetime()),
            open=float(row["Open"]),
            high=float(row["High"]),
            low=float(row["Low"]),
            close=float(row["Close"]),
            volume=int(row["Volume"]),
            open_interest=None,
            instrument_key=instrument_key,
            symbol=symbol,
            timeframe="1d",
            provider=self.name,
        )

    def health_check(self) -> bool:
        """Cheap real call -- one real day of Nifty 50 history, not a full sync."""
        try:
            history = yf.Ticker("^NSEI").history(period="1d")
            return not history.empty
        except Exception as exc:  # noqa: BLE001 -- a real, expected yfinance/network failure mode
            logger.warning("yfinance_health_check_failed", error=str(exc))
            return False

    @staticmethod
    def _to_ist(ts: datetime) -> datetime:
        """yfinance already returns tz-aware timestamps in the real exchange-local timezone for
        NSE tickers -- this only fills in Asia/Kolkata for the rare naive-timestamp case rather
        than assuming UTC, since a naive value here would otherwise silently be treated as UTC
        elsewhere in this codebase (spec §9's "Asia/Kolkata handling for Indian market data")."""
        if ts.tzinfo is None:
            return ts.replace(tzinfo=_IST)
        return ts.astimezone(UTC).astimezone(_IST)
