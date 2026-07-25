"""NSE bhavcopy adapter — primary EOD data source (free, official, no API key).

NSE publishes one CSV per trading day covering every listed symbol, under
https://archives.nseindia.com/products/content/sec_bhavdata_full_<DDMMYYYY>.csv
NSE occasionally changes this URL/format and rate-limits scrapers, so this
adapter is intentionally isolated behind EODDataSourceAdapter — swap
implementations without touching the ingestion pipeline or writer.
"""

from datetime import date, timedelta
from io import StringIO

import httpx
import polars as pl
import structlog

from src.data.ingest.base import EOD_SCHEMA, EODDataSourceAdapter

logger = structlog.get_logger(__name__)

BHAVCOPY_URL = "https://archives.nseindia.com/products/content/sec_bhavdata_full_{ddmmyyyy}.csv"
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/csv,*/*",
}


def _trading_days(start: date, end: date) -> list[date]:
    """Weekday calendar approximation; NSE holiday calendar refinement is a Phase 1 follow-up."""
    days = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


class BhavcopyAdapter(EODDataSourceAdapter):
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(
            headers=NSE_HEADERS, timeout=30.0, follow_redirects=True
        )

    def fetch(self, symbols: list[str], start: date, end: date) -> pl.DataFrame:
        symbol_set = set(symbols)
        frames: list[pl.DataFrame] = []
        for day in _trading_days(start, end):
            day_frame = self._fetch_day(day, symbol_set)
            if day_frame is not None and day_frame.height > 0:
                frames.append(day_frame)

        if not frames:
            return pl.DataFrame(schema={c: pl.Utf8 for c in EOD_SCHEMA})
        return pl.concat(frames).sort(["symbol", "date"])

    def _fetch_day(self, day: date, symbol_set: set[str]) -> pl.DataFrame | None:
        url = BHAVCOPY_URL.format(ddmmyyyy=day.strftime("%d%m%Y"))
        try:
            response = self._client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("bhavcopy_fetch_failed", day=day.isoformat(), error=str(exc))
            return None

        raw = pl.read_csv(StringIO(response.text))
        raw = raw.rename({c: c.strip() for c in raw.columns})

        df = raw.select(
            pl.col("SYMBOL").str.strip_chars().alias("symbol"),
            pl.lit(day).alias("date"),
            pl.col("OPEN_PRICE").str.strip_chars().cast(pl.Float64).alias("open"),
            pl.col("HIGH_PRICE").str.strip_chars().cast(pl.Float64).alias("high"),
            pl.col("LOW_PRICE").str.strip_chars().cast(pl.Float64).alias("low"),
            pl.col("CLOSE_PRICE").str.strip_chars().cast(pl.Float64).alias("close"),
            pl.col("TTL_TRD_QNTY").str.strip_chars().cast(pl.Int64).alias("volume"),
        )
        if symbol_set:
            df = df.filter(pl.col("symbol").is_in(symbol_set))
        return df
