"""Market data REST surface (REL-010 E10.8a, API-033..038).

All reads here are plain data lookups against real, already-ingested data (the Parquet EOD/
intraday lakes from REL-005/E10.7, the real `corporate_actions` table from E10.7, and the real
broker adapter for live quotes/option chains from E10.4) -- no endpoint here writes anything or
places an order. Left ungated, matching every other plain market-data-style read in this
codebase (src/api/routers/portfolio.py's `/positions`/`/portfolio/margin`, src/api/routers/
agents.py's `/runs`) -- these predate real JWT/RBAC (REL-007) and carry no execution authority.
"""

from datetime import date

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from src.brokers.base import OptionChain, Quote
from src.brokers.factory import NoBrokerConfigured, build_broker
from src.core.config import get_settings
from src.core.db import get_session
from src.data.datalake.query import DataLake, IntradayDataLake
from src.models.corporate_action import CorporateAction

router = APIRouter(prefix="/api/v1/market", tags=["market-data"])


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
    """API-034. Reads the real E10.7 minute-bar lake -- returns an empty list, not an error, if
    nothing has been ingested for this symbol/day yet (the intraday ingestion scheduler job runs
    only during real NSE market hours)."""
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
    """API-036. Real live broker quote (BrokerAdapter.get_quote), same broker-factory pattern as
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
    """API-037. Real live option chain via the E10.4 broker adapters (Kite's real /instruments +
    /quote, or Upstox's real instruments/quote endpoints), with locally-computed IV where the
    broker doesn't already return one."""
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
