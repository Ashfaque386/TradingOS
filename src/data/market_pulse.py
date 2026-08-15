"""Shared real market-pulse data: India VIX and NSE sector-index closes.

The raw yfinance fetch here is the exact same call `IndiaVixSkill`/`NseSectorDataSkill`
(src/agents/tools/skills.py) already make for the Market Analyst Agent's own use -- extracted to
this module (REL-067) so the agent's skill and `GET /market/pulse` read the literal same real
data path, never two implementations that could drift. The skills keep calling these functions
and keep their existing `{date, close}` return shape unchanged; `get_market_pulse()` below is the
only thing that additionally computes `change_pct`, from the same 5-day history already fetched
but never used beyond the latest close.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import cast

import pandas as pd
import structlog
import yfinance

logger = structlog.get_logger(__name__)

SECTOR_TICKERS = {
    "IT": "^CNXIT",
    "BANK": "^NSEBANK",
    "AUTO": "^CNXAUTO",
    "PHARMA": "^CNXPHARMA",
}


def fetch_india_vix_history() -> pd.DataFrame:
    """Real ^INDIAVIX 5-day daily history via yfinance."""
    return cast(pd.DataFrame, yfinance.Ticker("^INDIAVIX").history(period="5d", interval="1d"))


def fetch_sector_history(ticker: str) -> pd.DataFrame:
    """Real NSE sector-index 5-day daily history via yfinance for one ticker."""
    return cast(pd.DataFrame, yfinance.Ticker(ticker).history(period="5d", interval="1d"))


@dataclass(frozen=True)
class IndexPulse:
    name: str
    value: float
    change_pct: float
    as_of: date


@dataclass(frozen=True)
class MarketPulse:
    india_vix: IndexPulse | None
    sectors: list[IndexPulse]


def _to_pulse(name: str, history: pd.DataFrame) -> IndexPulse | None:
    """`change_pct` is the latest close vs. the previous session's close in the same history
    frame already fetched -- 0.0 only when a single session of history exists, never a
    fabricated 0 standing in for a real number we didn't compute."""
    if history.empty:
        return None
    close = float(history.iloc[-1]["Close"])
    as_of = history.index[-1].date()
    if len(history) >= 2:
        prev_close = float(history.iloc[-2]["Close"])
        change_pct = ((close - prev_close) / prev_close) * 100 if prev_close else 0.0
    else:
        change_pct = 0.0
    return IndexPulse(name=name, value=close, change_pct=change_pct, as_of=as_of)


def get_market_pulse() -> MarketPulse:
    """Real India VIX + real NSE sector-index day-change, for `GET /market/pulse`. An index
    whose yfinance call fails or returns no data is honestly omitted, matching
    `NseSectorDataSkill`'s own "one bad ticker shouldn't sink the others" precedent -- never a
    fabricated value standing in for a real one."""
    india_vix = _to_pulse("India VIX", fetch_india_vix_history())

    sectors: list[IndexPulse] = []
    for name, ticker in SECTOR_TICKERS.items():
        try:
            history = fetch_sector_history(ticker)
        except Exception as exc:  # yfinance raises assorted network/library errors
            logger.warning("sector_pulse_fetch_failed", sector=name, ticker=ticker, error=str(exc))
            continue
        pulse = _to_pulse(name, history)
        if pulse is not None:
            sectors.append(pulse)

    return MarketPulse(india_vix=india_vix, sectors=sectors)
