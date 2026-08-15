"""MarketDataManager (REL-070, Phase 1) -- the ONLY thing the ingestion pipeline and backtest
layer are allowed to call for real historical market data (spec's own rule: "the backtesting
engine must never directly call upstox()/yfinance()... all provider selection through
MarketDataManager"). Walks the configured provider chain per-instrument (never provider-wide
latching -- a real Upstox rejection for one symbol must not disable Upstox for every other
symbol in the same run), classifies failures per the spec's own differentiated policy, and
returns real provenance (which provider actually served the data) alongside the result.

Known Phase 1 boundary, stated honestly rather than worked around: `UpstoxV3Provider` needs a
real Upstox `instrument_key` (e.g. "NSE_EQ|INE002A01018"), not a bare symbol -- resolving
arbitrary symbols to real instrument_keys is Phase 2's job (REL-071, instrument discovery/sync),
not yet built. Until then, a caller that only has a bare symbol (e.g. the existing
`pipeline.py` CLI) passes it through as both `instrument_key` and `symbol`; Upstox will
correctly, honestly reject a bare symbol as a malformed instrument_key (matching Upstox's own
real UDAPI1021 "invalid format" error), and this manager will correctly fail over to yfinance --
a real, working failover, not a fake one, just not yet "Upstox serves real data for a
plain-typed symbol" (that needs Phase 2's real instrument resolution).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, date, datetime

import structlog

from src.core import vault
from src.core.config import Settings, get_settings
from src.data.providers.base import (
    Candle,
    DataQualityReport,
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
    ProviderUnsupportedIntervalError,
    Timeframe,
    validate_candles,
)
from src.data.providers.upstox_v3 import UpstoxV3Provider
from src.data.providers.yahoo_finance import YahooFinanceProvider

logger = structlog.get_logger(__name__)

# Non-retryable: retrying against the SAME provider can't succeed (a bad credential stays bad, a
# missing instrument stays missing, an unsupported interval stays unsupported) -- straight to
# the next provider in the chain.
_NON_RETRYABLE: tuple[type[ProviderError], ...] = (
    ProviderAuthError,
    ProviderInstrumentNotFoundError,
    ProviderUnsupportedIntervalError,
    ProviderEmptyDataError,
    ProviderInvalidDataError,
)
# Transient: worth a bounded retry with exponential backoff before falling over to the next
# provider.
_RETRYABLE: tuple[type[ProviderError], ...] = (
    ProviderTimeoutError,
    ProviderNetworkError,
    ProviderServerError,
    ProviderRateLimitError,
)


class MarketDataUnavailable(Exception):
    """Every configured provider failed for this instrument+window -- a real, honest terminal
    failure, never a silently empty/fabricated result. `errors` maps provider name -> the real
    reason it failed, for a caller that wants to report *why*, not just *that* it failed."""

    def __init__(self, message: str, *, errors: dict[str, str]) -> None:
        super().__init__(message)
        self.errors = errors


@dataclass(frozen=True)
class MarketDataResult:
    candles: list[Candle]
    provider_requested: str
    provider_used: str
    retrieved_at: datetime
    quality: DataQualityReport
    data_repair_mode: bool = False


class MarketDataManager:
    """`providers` is the real failover order (`[primary, fallback]` when both are configured,
    a single-element list when only one is -- same graceful-degradation shape as
    `src/brokers/factory.py::build_broker`)."""

    def __init__(
        self,
        providers: list[MarketDataProvider],
        *,
        max_retries: int = 3,
        backoff_factor: float = 1.0,
        enable_failover: bool = True,
    ) -> None:
        if not providers:
            raise ValueError("MarketDataManager needs at least one configured provider")
        self._providers = providers
        self._max_retries = max_retries
        self._backoff_factor = backoff_factor
        self._enable_failover = enable_failover

    def get_historical_data(
        self,
        *,
        instrument_key: str,
        symbol: str,
        start: date,
        end: date,
        timeframe: Timeframe = "1d",
    ) -> MarketDataResult:
        providers = self._providers if self._enable_failover else self._providers[:1]
        requested = providers[0].name
        errors: dict[str, str] = {}

        for provider in providers:
            logger.info(
                "market_data_request", provider=provider.name, symbol=symbol, timeframe=timeframe
            )
            if not provider.health_check():
                errors[provider.name] = "health check failed"
                logger.warning("provider_health_check_failed", provider=provider.name)
                continue
            try:
                candles = self._fetch_with_retry(
                    provider,
                    instrument_key=instrument_key,
                    symbol=symbol,
                    start=start,
                    end=end,
                    timeframe=timeframe,
                )
            except ProviderError as exc:
                errors[provider.name] = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "provider_failure",
                    provider=provider.name,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                continue

            quality = validate_candles(candles)
            if not quality.valid:
                # Spec §16: never silently repair -- a provider whose own data fails real OHLC
                # sanity checks is treated exactly like a provider failure, not "close enough."
                issue_kinds = [i.kind for i in quality.issues]
                errors[provider.name] = f"data quality: {issue_kinds}"
                logger.warning(
                    "provider_data_quality_failed", provider=provider.name, issues=issue_kinds
                )
                continue

            logger.info(
                "market_data_fetch_succeeded",
                provider_requested=requested,
                provider_used=provider.name,
                symbol=symbol,
                rows=len(candles),
            )
            if provider.name != requested:
                logger.info("market_data_failover", from_provider=requested, to=provider.name)
            return MarketDataResult(
                candles=candles,
                provider_requested=requested,
                provider_used=provider.name,
                retrieved_at=datetime.now(UTC),
                quality=quality,
            )

        raise MarketDataUnavailable(
            f"No configured provider could supply {symbol} ({instrument_key}) {start}..{end} "
            f"@ {timeframe}",
            errors=errors,
        )

    def _fetch_with_retry(
        self,
        provider: MarketDataProvider,
        *,
        instrument_key: str,
        symbol: str,
        start: date,
        end: date,
        timeframe: Timeframe,
    ) -> list[Candle]:
        last_exc: ProviderError | None = None
        for attempt in range(self._max_retries):
            try:
                return provider.get_historical_data(
                    instrument_key=instrument_key,
                    symbol=symbol,
                    start=start,
                    end=end,
                    timeframe=timeframe,
                )
            except _NON_RETRYABLE:
                raise
            except _RETRYABLE as exc:
                last_exc = exc
                if attempt < self._max_retries - 1:
                    time.sleep(self._backoff_factor * (2**attempt))
                    continue
        assert last_exc is not None  # the loop above always either returns or sets this
        raise last_exc


def build_market_data_manager(settings: Settings | None = None) -> MarketDataManager:
    """Real factory, same Vault-first/graceful-degradation shape as
    `src/brokers/factory.py::build_broker`: Upstox is only added to the chain when a real
    Analytics Token is configured (Vault first, then `.env`); yfinance needs no credential and
    is always available. If Upstox isn't configured, the manager simply runs yfinance alone --
    matching `build_broker`'s own "one adapter runs alone with no failover" precedent, not an
    error."""
    settings = settings or get_settings()

    available: dict[str, MarketDataProvider] = {"yfinance": YahooFinanceProvider()}
    token = vault.read_market_data_credential("upstox", settings=settings) or (
        settings.upstox_analytics_token
    )
    if token:
        available["upstox_v3"] = UpstoxV3Provider(token=token, timeout=settings.request_timeout)

    ordered: list[MarketDataProvider] = []
    primary = available.get(settings.primary_market_data_provider)
    fallback = available.get(settings.fallback_market_data_provider)
    if primary is not None:
        ordered.append(primary)
    if fallback is not None and fallback is not primary:
        ordered.append(fallback)
    if not ordered:
        ordered.append(available["yfinance"])

    return MarketDataManager(
        ordered,
        max_retries=settings.max_retries,
        backoff_factor=settings.backoff_factor,
        enable_failover=settings.enable_provider_failover,
    )
