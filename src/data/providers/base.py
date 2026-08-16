"""Market data provider abstraction (REL-070, Phase 1 of the Upstox V3 + yfinance dual
market-data system): the real historical-EOD ingestion path (`src/data/ingest/pipeline.py`) and
the real backtest data path (`src/engine/sandbox/backtest_runner.py`) must never call a specific
provider's client directly -- every real fetch goes through `MarketDataManager`
(src/data/providers/manager.py), which selects between concrete `MarketDataProvider`
implementations and fails over per-instrument.

Deliberately synchronous, matching the existing `EODDataSourceAdapter` (src/data/ingest/base.py)
this replaces the direct-use of: historical ingestion is a batch/background CLI or scheduled job
today, not a latency-sensitive execution path (unlike `BrokerAdapter`, src/brokers/base.py, which
is async for the live order pipeline's real <50ms NFR-02 budget) -- no real reason to introduce
async into a currently-sync ingestion pipeline for this.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

Timeframe = Literal["1m", "5m", "15m", "30m", "1h", "1d", "1w", "1mo"]


class ProviderError(Exception):
    """Base for every real, classified provider failure. `MarketDataManager` branches its
    retry/fallback policy on the concrete subclass (spec's own §13 differentiated-failover
    table), never on string-matching an error message."""


class ProviderAuthError(ProviderError):
    """Bad/missing credential -- not a transient condition, no retry."""


class ProviderTokenExpiredError(ProviderAuthError):
    """A credential that was valid once but no longer is -- immediate fallback, no retry
    (retrying with the same expired token can't succeed)."""


class ProviderRateLimitError(ProviderError):
    """The provider's own documented rate limit was hit -- back off, then fall back."""


class ProviderTimeoutError(ProviderError):
    """A real network timeout -- transient, worth a bounded retry before falling back."""


class ProviderNetworkError(ProviderError):
    """DNS/connection-level failure -- transient, worth a bounded retry before falling back."""


class ProviderServerError(ProviderError):
    """The provider's own 5xx -- transient, worth a bounded retry before falling back."""


class ProviderInstrumentNotFoundError(ProviderError):
    """This provider genuinely doesn't have the requested instrument -- not transient, no
    retry against the same provider, straight to fallback (or a real, honest failure if no
    fallback has it either)."""


class ProviderUnsupportedIntervalError(ProviderError):
    """The requested timeframe isn't one this provider's real API supports -- caught before
    ever making the HTTP call where the mapping is known statically (e.g.
    `UpstoxV3Provider.TIMEFRAME_MAP`), not just from a 4xx response."""


class ProviderEmptyDataError(ProviderError):
    """A real, successful response with zero candles -- distinct from "provider is down,"
    since an empty date range or a genuinely non-trading instrument both look like this."""


class ProviderInvalidDataError(ProviderError):
    """The response parsed, but failed real OHLC sanity checks (`validate_candles` below) --
    never silently repaired, per spec §16."""


@dataclass(frozen=True)
class Candle:
    """The one shape every provider normalizes into, and the only shape `MarketDataManager`
    hands onward -- callers never see a provider-specific response shape (spec §9). `timestamp`
    is timezone-aware (Asia/Kolkata for every real Indian-market instrument this system handles).
    `open_interest` is `None`, never a fabricated 0, whenever the provider doesn't report it
    (e.g. every real equity/index candle -- only F&O instruments carry real open interest)."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    open_interest: int | None
    instrument_key: str
    symbol: str
    timeframe: Timeframe
    provider: str


@dataclass(frozen=True)
class InstrumentHit:
    """A single real search/lookup result -- the shape `search_instrument`/`get_instruments`
    return. REL-071 (Phase 2) found Upstox has no live per-call search API at all (its real
    mechanism is a daily-refreshed static file, see src/data/ingest/instrument_sync.py) --
    so the real, working implementation lives against the locally-synced `instruments` table in
    src/data/instruments.py (`search`, `get_equities`, `get_indices`, `resolve_instrument_key`),
    not on this provider interface. These two methods stay unimplemented here, on purpose: a
    provider genuinely has no live search call to make."""

    instrument_key: str
    symbol: str
    name: str
    exchange: str
    segment: str
    instrument_type: str


@dataclass(frozen=True)
class DataQualityIssue:
    kind: Literal[
        "duplicate_timestamp",
        "invalid_ohlc",
        "negative_volume",
        "unsorted",
        "missing_field",
    ]
    detail: str


@dataclass(frozen=True)
class DataQualityReport:
    valid: bool
    issues: list[DataQualityIssue] = field(default_factory=list)


def validate_candles(candles: list[Candle]) -> DataQualityReport:
    """Spec §16: real OHLC sanity checks, run on every result before it ever reaches a caller --
    never a silent repair. `candles` is NOT mutated or re-sorted here; a caller that wants sorted
    output does that itself once it has decided the report is `valid`."""
    issues: list[DataQualityIssue] = []
    seen_timestamps: set[datetime] = set()
    previous_timestamp: datetime | None = None
    for candle in candles:
        if candle.timestamp in seen_timestamps:
            issues.append(
                DataQualityIssue("duplicate_timestamp", f"{candle.timestamp.isoformat()}")
            )
        seen_timestamps.add(candle.timestamp)

        if previous_timestamp is not None and candle.timestamp < previous_timestamp:
            detail = f"{candle.timestamp.isoformat()} follows {previous_timestamp.isoformat()}"
            issues.append(DataQualityIssue("unsorted", detail))
        previous_timestamp = candle.timestamp

        if candle.volume < 0:
            issues.append(DataQualityIssue("negative_volume", f"{candle.timestamp.isoformat()}"))

        ohlc_valid = (
            candle.high >= candle.low
            and candle.high >= candle.open
            and candle.high >= candle.close
            and candle.low <= candle.open
            and candle.low <= candle.close
        )
        if not ohlc_valid:
            issues.append(
                DataQualityIssue(
                    "invalid_ohlc",
                    f"{candle.timestamp.isoformat()}: O={candle.open} H={candle.high} "
                    f"L={candle.low} C={candle.close}",
                )
            )

    return DataQualityReport(valid=len(issues) == 0, issues=issues)


class MarketDataProvider(ABC):
    """A concrete provider (`UpstoxV3Provider`, `YahooFinanceProvider`) implements every method
    against one real data source. `MarketDataManager` depends only on this interface."""

    name: str

    @abstractmethod
    def get_historical_data(
        self,
        *,
        instrument_key: str,
        symbol: str,
        start: date,
        end: date,
        timeframe: Timeframe,
    ) -> list[Candle]:
        """Raises a `ProviderError` subclass on any real failure -- never returns an empty list
        to mean "something went wrong" (that's `ProviderEmptyDataError`) vs. "genuinely no
        trading happened in this window" (also `ProviderEmptyDataError` -- the caller can't and
        shouldn't need to distinguish the two; both mean "this provider has nothing for this
        request")."""
        ...

    @abstractmethod
    def get_latest_data(self, *, instrument_key: str, symbol: str) -> Candle | None:
        """The most recent real quote/candle, or `None` if genuinely unavailable -- never a
        stale cached value presented as current."""
        ...

    def search_instrument(self, query: str) -> list[InstrumentHit]:
        """Not implemented here -- REL-071 (Phase 2) found this provider has no live per-call
        search API to wrap (Upstox's real instrument discovery is a daily static file, not a
        query endpoint). Use `src.data.instruments.search()` against the real, locally-synced
        `instruments` table instead. Left concrete-but-raising (not abstract) so existing/new
        providers don't need a premature implementation; the default raises rather than
        returning a fabricated empty result."""
        raise NotImplementedError(
            f"{self.name}: no live instrument search API -- use src.data.instruments.search()"
        )

    def get_instruments(self, *, exchange: str, segment: str | None = None) -> list[InstrumentHit]:
        """Not implemented here, same reason as `search_instrument` above -- use
        `src.data.instruments.get_equities()`/`get_indices()` against the real, locally-synced
        `instruments` table instead."""
        raise NotImplementedError(
            f"{self.name}: no live instrument listing API -- use src.data.instruments module"
        )

    @abstractmethod
    def health_check(self) -> bool:
        """A cheap, real call proving this provider is currently reachable and authenticated --
        never a full historical-data download."""
        ...
