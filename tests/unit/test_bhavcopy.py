"""BhavcopyAdapter unit tests. Every HTTP call is mocked via `httpx.MockTransport`, matching
tests/unit/test_upstox_v3_provider.py's own established pattern -- no real network call.

Found during a post-KPI-dashboard-review coverage audit: this "primary EOD data source"
(bhavcopy.py's own module docstring) had zero dedicated tests -- specifically untested was
`_fetch_day()`'s own `except httpx.HTTPError` path, the exact failure mode its module docstring
warns about ("NSE occasionally changes this URL/format and rate-limits scrapers").
"""

from datetime import date

import httpx
import polars as pl

from src.data.ingest.bhavcopy import BhavcopyAdapter

_DAY_1 = date(2026, 8, 3)  # a Monday -- both days are real trading days, no holiday involved
_DAY_2 = date(2026, 8, 4)

_REAL_CSV_BODY = (
    "SYMBOL , SERIES ,OPEN_PRICE ,HIGH_PRICE ,LOW_PRICE ,CLOSE_PRICE ,LAST_PRICE ,"
    "PREV_CLOSE ,TTL_TRD_QNTY ,TURNOVER_LACS ,NO_OF_TRADES ,DELIV_QTY ,DELIV_PER \n"
    "RELIANCE ,EQ ,2900.00 ,2950.00 ,2890.00 ,2940.00 ,2940.00 ,2895.00 ,1000000 ,"
    "29000.00 ,50000 ,500000 ,50.00\n"
)


def _adapter_with_transport(handler) -> BhavcopyAdapter:
    adapter = BhavcopyAdapter()
    adapter._client = httpx.Client(
        headers=adapter._client.headers,
        timeout=adapter._client.timeout,
        transport=httpx.MockTransport(handler),
    )
    return adapter


def test_fetch_degrades_gracefully_when_one_days_request_fails():
    """A real, confirmed failure mode: NSE 404s/rate-limits one day's own bhavcopy URL while
    another day in the same range succeeds -- `fetch()` must still return the other day's real
    data, not lose the whole multi-day run or raise."""

    def handler(request: httpx.Request) -> httpx.Response:
        if _DAY_1.strftime("%d%m%Y") in str(request.url):
            return httpx.Response(200, text=_REAL_CSV_BODY)
        return httpx.Response(404, text="Not Found")

    adapter = _adapter_with_transport(handler)

    result = adapter.fetch(["RELIANCE"], _DAY_1, _DAY_2)

    assert result.height == 1
    assert result["symbol"].to_list() == ["RELIANCE"]
    assert result["date"].to_list() == [_DAY_1]
    assert result["close"].to_list() == [2940.00]


def test_fetch_returns_an_empty_typed_frame_when_every_day_fails():
    """The real degradation floor: every day 404s -- still an empty DataFrame with the right
    schema, not a crash or a None, matching EOD_SCHEMA (src/data/ingest/base.py)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="Not Found")

    adapter = _adapter_with_transport(handler)

    result = adapter.fetch(["RELIANCE"], _DAY_1, _DAY_2)

    assert isinstance(result, pl.DataFrame)
    assert result.height == 0
    assert set(result.columns) == {"symbol", "date", "open", "high", "low", "close", "volume"}


def test_fetch_filters_to_only_the_requested_symbols():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_REAL_CSV_BODY)

    adapter = _adapter_with_transport(handler)

    result = adapter.fetch(["WIPRO"], _DAY_1, _DAY_1)

    assert result.height == 0
