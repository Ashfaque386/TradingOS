"""Upstox V3 market-data provider (REL-070, Phase 1). Real Historical Candle Data V3 API,
confirmed against Upstox's own current developer documentation
(https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/) at
implementation time -- not the legacy V2 endpoint `src/brokers/upstox_adapter.py` already uses
for live-trading order placement (a different concern, a different credential).

Always targets the real production host (`https://api.upstox.com/v3`), never a sandbox variant:
the Analytics Token this provider authenticates with is inherently production-scoped, read-only
market data (no order-placement capability, so no funds-risk concern from hitting production
directly) -- and `UpstoxAdapter.get_historical_candles`'s own docstring already empirically
confirmed Upstox's sandbox 404s on historical market data entirely, so a sandbox toggle here
would have nothing to point at anyway.

Real, confirmed API contract (fetched from the live docs, not invented):
  - `GET /v3/historical-candle/{instrument_key}/{unit}/{interval}/{to_date}/{from_date}`
  - `unit` in {minutes, hours, days, weeks, months}; `interval` per unit: minutes 1-300,
    hours 1-5, days/weeks/months exactly 1 -- see TIMEFRAME_MAP.
  - Response: `{"status": ..., "data": {"candles": [[timestamp, open, high, low, close, volume,
    open_interest], ...]}}`.
  - Error envelope (confirmed via UpstoxAdapter's own real empirical finding):
    `{"status": "error", "errors": [{"errorCode": "UDAPI...", "message": "..."}]}`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import quote

import httpx
import structlog

from src.data.providers.base import (
    Candle,
    MarketDataProvider,
    ProviderAuthError,
    ProviderEmptyDataError,
    ProviderError,
    ProviderInstrumentNotFoundError,
    ProviderInvalidDataError,
    ProviderNetworkError,
    ProviderRateLimitError,
    ProviderServerError,
    ProviderTimeoutError,
    ProviderTokenExpiredError,
    ProviderUnsupportedIntervalError,
    Timeframe,
)

logger = structlog.get_logger(__name__)

UPSTOX_V3_BASE_URL = "https://api.upstox.com/v3"

# Real, confirmed (unit, interval) pairs -- never send a value outside this map to the real API.
TIMEFRAME_MAP: dict[Timeframe, tuple[str, str]] = {
    "1m": ("minutes", "1"),
    "5m": ("minutes", "5"),
    "15m": ("minutes", "15"),
    "30m": ("minutes", "30"),
    "1h": ("hours", "1"),
    "1d": ("days", "1"),
    "1w": ("weeks", "1"),
    "1mo": ("months", "1"),
}

# Real Upstox error codes (confirmed against the live docs) mapped onto this codebase's own
# ProviderError hierarchy -- an unrecognized code falls through to a generic ProviderError
# rather than being silently swallowed or mis-classified.
_ERROR_CODE_MAP: dict[str, type[ProviderError]] = {
    "UDAPI1021": ProviderInstrumentNotFoundError,  # instrument key malformed
    "UDAPI100011": ProviderInstrumentNotFoundError,  # instrument key invalid
    "UDAPI1146": ProviderUnsupportedIntervalError,  # invalid unit
    "UDAPI1147": ProviderUnsupportedIntervalError,  # invalid interval
    "UDAPI1015": ProviderInvalidDataError,  # to_date < from_date
    "UDAPI1022": ProviderInvalidDataError,  # to_date missing
    "UDAPI1148": ProviderInvalidDataError,  # invalid date range
}


class UpstoxV3Provider(MarketDataProvider):
    name = "upstox_v3"

    def __init__(self, *, token: str, timeout: float = 10.0) -> None:
        self._client = httpx.Client(
            base_url=UPSTOX_V3_BASE_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> UpstoxV3Provider:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def get_historical_data(
        self,
        *,
        instrument_key: str,
        symbol: str,
        start: date,
        end: date,
        timeframe: Timeframe,
    ) -> list[Candle]:
        if timeframe not in TIMEFRAME_MAP:
            raise ProviderUnsupportedIntervalError(
                f"upstox_v3 does not support timeframe={timeframe!r}"
            )
        unit, interval = TIMEFRAME_MAP[timeframe]

        # Real path order is to_date THEN from_date, confirmed against the live docs -- easy to
        # get backwards since every other convention in this codebase (backtest date_from/
        # date_to, DataLake.read_symbol) puts the earlier date first.
        path = (
            f"/historical-candle/{quote(instrument_key, safe='')}/{unit}/{interval}"
            f"/{end.isoformat()}/{start.isoformat()}"
        )
        payload = self._get(path)
        raw_candles: list[list[Any]] = payload["data"]["candles"]

        if not raw_candles:
            raise ProviderEmptyDataError(
                f"upstox_v3 returned zero candles for {symbol} ({instrument_key}) "
                f"{start}..{end} @ {timeframe}"
            )

        candles = [
            Candle(
                timestamp=datetime.fromisoformat(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=int(row[5]),
                open_interest=int(row[6]) if row[6] is not None else None,
                instrument_key=instrument_key,
                symbol=symbol,
                timeframe=timeframe,
                provider=self.name,
            )
            for row in raw_candles
        ]
        # REL-078: the real API responds newest-first for a multi-day range (confirmed
        # empirically against a real futures instrument_key this session) -- validate_candles()
        # (src/data/providers/base.py) deliberately never re-sorts ("a caller that wants sorted
        # output does that itself"), so normalizing this provider's own known response-order
        # convention belongs here, not there. Equity/index fetches have almost certainly been
        # hitting the same "unsorted" rejection all along, silently masked by yfinance failover;
        # for futures there is no failover, so this was a hard, total block until fixed.
        candles.sort(key=lambda c: c.timestamp)
        return candles

    def get_latest_data(self, *, instrument_key: str, symbol: str) -> Candle | None:
        """Real Market Quote OHLC V3 endpoint (`GET /v3/market-quote/ohlc`)."""
        payload = self._get("/market-quote/ohlc", params={"instrument_key": instrument_key})
        quotes: dict[str, Any] = payload.get("data", {})
        if not quotes:
            return None
        quote_data = next(iter(quotes.values()))
        live = quote_data.get("live_ohlc") or quote_data.get("ohlc")
        if not live:
            return None
        return Candle(
            timestamp=(
                datetime.fromtimestamp(live["ts"], tz=UTC) if live.get("ts") else datetime.now(UTC)
            ),
            open=float(live["open"]),
            high=float(live["high"]),
            low=float(live["low"]),
            close=float(live["close"]),
            volume=int(live.get("volume", 0)),
            open_interest=None,
            instrument_key=instrument_key,
            symbol=symbol,
            timeframe="1d",
            provider=self.name,
        )

    def health_check(self) -> bool:
        """Cheap real call -- one day of Nifty 50 daily candles, not a full sync. `NSE_INDEX|Nifty
        50` is a real, stable Upstox instrument_key (confirmed against the live instrument
        master schema -- indices use the `NSE_INDEX`/`BSE_INDEX` segment)."""
        today = date.today()
        try:
            self._get(
                f"/historical-candle/{quote('NSE_INDEX|Nifty 50', safe='')}/days/1"
                f"/{today.isoformat()}/{today.isoformat()}"
            )
            return True
        except ProviderError as exc:
            logger.warning("upstox_v3_health_check_failed", error=str(exc))
            return False

    def _get(self, path: str, *, params: dict[str, str] | None = None) -> dict[str, Any]:
        try:
            response = self._client.get(path, params=params)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(f"upstox_v3 request to {path} timed out") from exc
        except httpx.NetworkError as exc:
            raise ProviderNetworkError(f"upstox_v3 network error for {path}: {exc}") from exc

        if response.status_code == 401:
            raise ProviderTokenExpiredError("upstox_v3 rejected the Analytics Token (401)")
        if response.status_code == 403:
            raise ProviderAuthError("upstox_v3 denied access (403)")
        if response.status_code == 429:
            raise ProviderRateLimitError("upstox_v3 rate limit exceeded (429)")
        if response.status_code >= 500:
            raise ProviderServerError(f"upstox_v3 server error {response.status_code}")
        if response.status_code >= 400:
            self._raise_for_error_body(response)

        return response.json()  # type: ignore[no-any-return]

    def _raise_for_error_body(self, response: httpx.Response) -> None:
        """Real Upstox error envelope: `{"status":"error","errors":[{"errorCode":"UDAPI...",
        ...}]}` -- confirmed empirically against the live API (see UpstoxAdapter's own module
        docstring). Falls back to a generic ProviderError if the body doesn't parse as JSON or
        doesn't carry a recognized code, rather than guessing."""
        try:
            body = response.json()
            errors = body.get("errors", [])
            code = errors[0].get("errorCode") if errors else None
        except Exception:  # noqa: BLE001 -- a non-JSON error body is a real, if unusual, case
            code = None
        error_cls = _ERROR_CODE_MAP.get(code, ProviderError) if code else ProviderError
        message = f"upstox_v3 error {response.status_code}: {response.text}"
        raise error_cls(message)
