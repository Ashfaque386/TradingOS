"""Market data REST surface (REL-010 E10.8a, API-033..038).

All reads here are plain data lookups against real, already-ingested data (the Parquet EOD/
intraday lakes from REL-005/E10.7, the real `corporate_actions` table from E10.7, and the real
broker adapter for live quotes/option chains from E10.4) -- no endpoint here writes anything or
places an order. Left ungated, matching every other plain market-data-style read in this
codebase (src/api/routers/portfolio.py's `/positions`/`/portfolio/margin`, src/api/routers/
agents.py's `/runs`) -- these predate real JWT/RBAC (REL-007) and carry no execution authority.

REL-055: `POST /ingest/trigger` is a genuine write action -- unlike everything else in this
file, it's gated (SystemAdministrator only, an infra/ops action). Reuses
`strategies.py`'s exact background-job pattern (`_BacktestJob`/`threading.Thread(daemon=True)`,
`strategies.py:365-548`) because `src.data.ingest.pipeline.run()` is synchronous, blocking
network I/O (real bhavcopy/yfinance calls) that would stall the event loop if awaited directly
inside an `async def` handler.
"""

import threading
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from src.api.deps import require_role
from src.brokers.base import OptionChain, Quote
from src.brokers.factory import NoBrokerConfigured, build_broker
from src.core.config import get_settings
from src.core.db import get_session
from src.core.security import ROLE_SYSTEM_ADMINISTRATOR
from src.data.datalake.freshness import check_freshness
from src.data.datalake.query import DataLake, IntradayDataLake
from src.data.features.indicators import with_indicators
from src.data.ingest.pipeline import ADAPTERS, MANAGED_SOURCE
from src.data.ingest.pipeline import run as run_ingestion
from src.data.instruments import search as search_instruments
from src.data.market_pulse import get_market_pulse
from src.models.corporate_action import CorporateAction
from src.models.user import User

router = APIRouter(prefix="/api/v1/market", tags=["market-data"])

_can_trigger_ingest = require_role(ROLE_SYSTEM_ADMINISTRATOR, audit_denials=True)


class OhlcvBar(BaseModel):
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int


class IntradayBar(BaseModel):
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class CorporateActionResponse(BaseModel):
    symbol: str
    ex_date: date
    action_type: str
    ratio_numerator: float | None
    ratio_denominator: float | None
    dividend_amount: float | None
    source: str


def _daily_lake() -> DataLake:
    return DataLake(get_settings().data_lake_root / "ohlcv_daily")


@router.get("/symbols", response_model=list[str])
def list_symbols() -> list[str]:
    """API-038. Real symbols actually ingested into the daily EOD lake -- not a configured or
    fabricated universe (same source `DataLake.list_symbols()` already used by the Scheduler's
    Data Freshness gate)."""
    return _daily_lake().list_symbols()


class SymbolFreshness(BaseModel):
    symbol: str
    is_fresh: bool
    expected_date: date
    latest_available: date | None


class DatalakeStatusResponse(BaseModel):
    status: Literal["Fresh", "Stale"]
    as_of: date
    total_symbols: int
    stale_symbols: list[SymbolFreshness]


@router.get("/datalake/status", response_model=DatalakeStatusResponse)
def get_datalake_status(as_of: date | None = None) -> DatalakeStatusResponse:
    """API-037 (SRS Business Rule 4). Reuses `check_freshness()`
    (src/data/datalake/freshness.py) -- the exact same real, NSE-holiday-calendar-aware check
    `src/engine/backtest/data_feed.py` and the Scheduler's own pre-research-cycle gate
    (src/agents/scheduler.py) already enforce before a backtest or research cycle can run -- run
    across every symbol currently in the daily EOD lake, so this can never drift from what those
    real gates actually see. An empty lake (nothing ingested yet) reports Stale, not Fresh --
    there being no data to check is not the same as the data being current."""
    reference = as_of or date.today()
    lake = _daily_lake()
    symbols = lake.list_symbols()
    stale = [
        SymbolFreshness(
            symbol=result.symbol,
            is_fresh=result.is_fresh,
            expected_date=result.expected_date,
            latest_available=result.latest_available,
        )
        for symbol in symbols
        for result in [check_freshness(lake, symbol, reference)]
        if not result.is_fresh
    ]
    return DatalakeStatusResponse(
        status="Fresh" if symbols and not stale else "Stale",
        as_of=reference,
        total_symbols=len(symbols),
        stale_symbols=stale,
    )


class MarketPulseIndex(BaseModel):
    name: str
    value: float
    change_pct: float
    as_of: date


class MarketPulseResponse(BaseModel):
    india_vix: MarketPulseIndex | None
    sectors: list[MarketPulseIndex]


@router.get("/pulse", response_model=MarketPulseResponse)
def get_pulse() -> MarketPulseResponse:
    """REL-067. Real India VIX + NSE sector-index day-change, via the same
    `src.data.market_pulse.get_market_pulse()` the Market Analyst Agent's own `IndiaVixSkill`/
    `NseSectorDataSkill` (src/agents/tools/skills.py) fetch through -- this endpoint and the
    agent read the literal same real data path, never two implementations that could drift.
    `india_vix` is `None` and/or `sectors` can be a shorter list than 4 if yfinance had no data
    for one or more tickers at request time -- honestly omitted, never a fabricated value."""
    pulse = get_market_pulse()
    india_vix = (
        MarketPulseIndex(
            name=pulse.india_vix.name,
            value=pulse.india_vix.value,
            change_pct=pulse.india_vix.change_pct,
            as_of=pulse.india_vix.as_of,
        )
        if pulse.india_vix is not None
        else None
    )
    sectors = [
        MarketPulseIndex(name=s.name, value=s.value, change_pct=s.change_pct, as_of=s.as_of)
        for s in pulse.sectors
    ]
    return MarketPulseResponse(india_vix=india_vix, sectors=sectors)


class IndicatorPoint(BaseModel):
    date: date
    close: float
    sma_20: float | None
    ema_20: float | None
    rsi_14: float | None
    atr_14: float | None
    bb_upper: float | None
    bb_mid: float | None
    bb_lower: float | None
    macd_line: float | None
    macd_signal: float | None
    macd_histogram: float | None


@router.get("/ohlcv/{symbol}/indicators", response_model=list[IndicatorPoint])
def get_ohlcv_indicators(
    symbol: str, start: date | None = None, end: date | None = None
) -> list[IndicatorPoint]:
    """REL-067. Wires `src.data.features.indicators.with_indicators()` -- a complete, correct
    Polars indicators module with zero callers anywhere before this endpoint -- against the real
    daily OHLCV lake, the exact same source `GET /ohlcv/{symbol}` above already reads. Leading
    rows where a rolling window (e.g. `sma_20`) has fewer than `window` prior bars come back with
    that field `null`, not a fabricated early value."""
    df = _daily_lake().read_symbol(symbol, start=start, end=end)
    if df.height == 0:
        return []
    enriched = with_indicators(df)
    return [
        IndicatorPoint(
            date=row["date"],
            close=row["close"],
            sma_20=row["sma_20"],
            ema_20=row["ema_20"],
            rsi_14=row["rsi_14"],
            atr_14=row["atr_14"],
            bb_upper=row["bb_upper"],
            bb_mid=row["bb_mid"],
            bb_lower=row["bb_lower"],
            macd_line=row["macd_line"],
            macd_signal=row["macd_signal"],
            macd_histogram=row["macd_histogram"],
        )
        for row in enriched.to_dicts()
    ]


@router.get("/ohlcv/{symbol}", response_model=list[OhlcvBar])
def get_daily_ohlcv(
    symbol: str, start: date | None = None, end: date | None = None
) -> list[OhlcvBar]:
    """API-033."""
    df = _daily_lake().read_symbol(symbol, start=start, end=end)
    return [
        OhlcvBar(
            date=row["date"],
            open=row["open"],
            high=row["high"],
            low=row["low"],
            close=row["close"],
            volume=row["volume"],
        )
        for row in df.to_dicts()
    ]


@router.get("/ohlcv-intraday/{symbol}", response_model=list[IntradayBar])
def get_intraday_ohlcv(symbol: str, day: date | None = None) -> list[IntradayBar]:
    """Not tracked under its own API Traceability row (confirmed 2026-08-14: no row anywhere in
    the sheet mentions intraday OHLCV) -- previously mislabeled "API-034" here, which is actually
    `/market/quote/{symbol}` (see get_quote() below). Reads the real E10.7 minute-bar lake --
    returns an empty list, not an error, if nothing has been ingested for this symbol/day yet
    (the intraday ingestion scheduler job runs only during real NSE market hours)."""
    lake = IntradayDataLake(get_settings().data_lake_root / "ohlcv_intraday")
    df = lake.read_symbol(symbol, day=day)
    return [
        IntradayBar(
            timestamp=row["timestamp"].isoformat(),
            open=row["open"],
            high=row["high"],
            low=row["low"],
            close=row["close"],
            volume=row["volume"],
        )
        for row in df.to_dicts()
    ]


@router.get("/corporate-actions/{symbol}", response_model=list[CorporateActionResponse])
def get_corporate_actions(symbol: str) -> list[CorporateActionResponse]:
    """API-035. Real rows from the E10.7 `corporate_actions` table (hand-maintained real CSV
    source -- see src/data/ingest/corporate_actions.py's own docstring for why NSE has no live
    corporate-actions API to scrape instead)."""
    with get_session() as session:
        rows = session.scalars(
            select(CorporateAction)
            .where(CorporateAction.symbol == symbol)
            .order_by(CorporateAction.ex_date)
        )
        return [
            CorporateActionResponse(
                symbol=row.symbol,
                ex_date=row.ex_date,
                action_type=row.action_type,
                ratio_numerator=row.ratio_numerator,
                ratio_denominator=row.ratio_denominator,
                dividend_amount=row.dividend_amount,
                source=row.source,
            )
            for row in rows
        ]


@router.get("/quote/{symbol}", response_model=Quote)
async def get_quote(symbol: str) -> Quote:
    """API-034 (previously mislabeled "API-036" here, which is actually
    `/market/ingest/trigger`; see trigger_ingest() below). Real live broker quote
    (BrokerAdapter.get_quote), same broker-factory pattern as
    src/api/routers/portfolio.py's `_get_broker()`."""
    try:
        broker = build_broker()
    except NoBrokerConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        return await broker.get_quote(symbol)
    except httpx.HTTPStatusError as exc:
        # E.g. an expired daily Zerodha/Upstox access token (both expire every trading day, no
        # refresh token -- a documented constraint, not something this endpoint can paper over).
        raise HTTPException(status_code=502, detail=f"Broker quote request failed: {exc}") from exc


@router.get("/option-chain/{underlying}", response_model=OptionChain)
async def get_option_chain(underlying: str, expiry: date) -> OptionChain:
    """Not tracked under its own API Traceability row (confirmed 2026-08-14: no row anywhere in
    the sheet mentions option chains) -- previously mislabeled "API-037" here, which is actually
    `/market/datalake/status` (see get_datalake_status() above). Real live option chain via the
    E10.4 broker adapters (Kite's real /instruments + /quote, or Upstox's real instruments/quote
    endpoints), with locally-computed IV where the broker doesn't already return one."""
    try:
        broker = build_broker()
    except NoBrokerConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        return await broker.get_option_chain(underlying, expiry)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502, detail=f"Broker option-chain request failed: {exc}"
        ) from exc


@dataclass
class _IngestJob:
    status: Literal["Running", "Completed", "Failed"]
    error: str | None = None
    rows_written: int | None = None


_ingest_jobs: dict[str, _IngestJob] = {}
_ingest_jobs_lock = threading.Lock()


class IngestTriggerRequest(BaseModel):
    # REL-071: "managed" (the real Upstox V3 + yfinance automatic-failover path added in REL-070)
    # was missing here entirely -- this endpoint could only reach the two single-source adapters
    # directly, a real gap between what the CLI (src/data/ingest/pipeline.py) could already do
    # and what this REST trigger could ask for.
    source: Literal["bhavcopy", "yfinance", "managed"]
    symbols: list[str]
    start: date
    end: date


class IngestTriggerResponse(BaseModel):
    job_id: str
    status: str


class IngestJobStatusResponse(BaseModel):
    job_id: str
    status: str
    error: str | None
    rows_written: int | None


def _run_ingest_job(
    *, job_id: str, source: str, symbols: list[str], start: date, end: date
) -> None:
    try:
        written = run_ingestion(source, symbols, start, end)
    except Exception as exc:  # noqa: BLE001 -- a real, unpredictable adapter/network failure
        # must land in the job's own status, not crash this daemon thread silently.
        with _ingest_jobs_lock:
            _ingest_jobs[job_id] = _IngestJob(status="Failed", error=str(exc))
        return
    with _ingest_jobs_lock:
        _ingest_jobs[job_id] = _IngestJob(status="Completed", rows_written=written)


@router.post("/ingest/trigger", response_model=IngestTriggerResponse, status_code=202)
def trigger_ingest(
    body: IngestTriggerRequest, _user: User = Depends(_can_trigger_ingest)
) -> IngestTriggerResponse:
    """API-036. Manually trigger the same real EOD ingestion `python -m
    src.data.ingest.pipeline` already performs from the CLI -- run in a background thread
    (mirrors strategies.py's own backtest-trigger job pattern) since the real fetch/write is
    synchronous, blocking I/O that would stall the event loop if awaited directly here."""
    if body.source != MANAGED_SOURCE and body.source not in ADAPTERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown source -- choices are {sorted({MANAGED_SOURCE, *ADAPTERS})}",
        )
    if not body.symbols:
        raise HTTPException(status_code=400, detail="symbols must not be empty")

    job_id = str(uuid.uuid4())
    with _ingest_jobs_lock:
        _ingest_jobs[job_id] = _IngestJob(status="Running")

    threading.Thread(
        target=_run_ingest_job,
        kwargs={
            "job_id": job_id,
            "source": body.source,
            "symbols": [s.strip().upper() for s in body.symbols if s.strip()],
            "start": body.start,
            "end": body.end,
        },
        daemon=True,
    ).start()

    return IngestTriggerResponse(job_id=job_id, status="Running")


@router.get("/ingest/jobs/{job_id}/status", response_model=IngestJobStatusResponse)
def get_ingest_job_status(job_id: str) -> IngestJobStatusResponse:
    """Polls one specific trigger_ingest() job's real status/row-count -- NOT the same thing as
    API-037's own "/market/datalake/status -- data freshness/partition completeness check",
    which asks a different question (is the lake as a whole current) regardless of any specific
    trigger call. API-037 stays genuinely open; this only closes API-036."""
    with _ingest_jobs_lock:
        job = _ingest_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown ingest job (or the app restarted)")
    return IngestJobStatusResponse(
        job_id=job_id, status=job.status, error=job.error, rows_written=job.rows_written
    )


class InstrumentSummary(BaseModel):
    instrument_key: str
    exchange: str
    segment: str
    symbol: str
    name: str
    instrument_type: str
    isin: str | None


class InstrumentSearchResponse(BaseModel):
    items: list[InstrumentSummary]
    total: int
    page: int
    page_size: int


@router.get("/instruments/search", response_model=InstrumentSearchResponse)
def search_instruments_endpoint(
    q: str | None = None,
    exchange: str | None = None,
    instrument_type: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
) -> InstrumentSearchResponse:
    """REL-071 (Phase 2). Real, locally-synced Upstox instrument master
    (src/data/ingest/instrument_sync.py) -- searches `symbol` and `name` (Upstox's own Nifty 50
    row has symbol="NIFTY" but name="Nifty 50", so both are checked; see
    src/data/instruments.py). This is the first real server-side paginated search in this API --
    the daily-sync table can hold thousands of NSE/BSE rows, unlike API-038's `/symbols`, which
    only ever lists what's already been ingested into the EOD lake."""
    with get_session() as session:
        rows, total = search_instruments(
            session,
            query=q,
            exchange=exchange,
            instrument_type=instrument_type,
            page=page,
            page_size=page_size,
        )
        items = [
            InstrumentSummary(
                instrument_key=row.instrument_key,
                exchange=row.exchange,
                segment=row.segment,
                symbol=row.symbol,
                name=row.name,
                instrument_type=row.instrument_type,
                isin=row.isin,
            )
            for row in rows
        ]
    return InstrumentSearchResponse(items=items, total=total, page=page, page_size=page_size)
