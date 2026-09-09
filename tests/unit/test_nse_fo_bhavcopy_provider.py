"""NseFoBhavcopyProvider unit tests (REL-091). Every HTTP call is mocked via
`httpx.MockTransport` (same pattern as tests/unit/test_upstox_v3_provider.py) -- no real
network call, no real NSE download. The CSV fixtures mirror the real UDiFF F&O bhavcopy layout
(and the pre-2024-07-08 legacy layout) rather than an invented shape.
"""

from __future__ import annotations

import contextlib
import io
import re as _re
import time as _time
import zipfile
from datetime import date
from pathlib import Path

import httpx
import pytest

from src.data.providers.base import (
    ProviderEmptyDataError,
    ProviderInstrumentNotFoundError,
    ProviderUnsupportedIntervalError,
)
from src.data.providers.nse_fo_bhavcopy import NseFoBhavcopyProvider, parse_fo_symbol

# -- fixtures ------------------------------------------------------------------------------------

_UDIFF_HEADER = (
    "TradDt,BizDt,Sgmt,FinInstrmTp,TckrSymb,XpryDt,StrkPric,OptnTp,"
    "OpnPric,HghPric,LwPric,ClsPric,SttlmPric,OpnIntrst,TtlTradgVol,TtlTrfVal"
)


def _udiff_row(
    *,
    trad_dt: str,
    tckr: str = "NIFTY",
    xpry: str = "2026-09-08",
    strike: str = "22300",
    opt: str = "CE",
    fin_tp: str = "IDO",
    o: str = "1500",
    h: str = "1560",
    low: str = "1490",
    c: str = "1520",
    oi: str = "250000",
    vol: str = "12000",
) -> str:
    return (
        f"{trad_dt},{trad_dt},FO,{fin_tp},{tckr},{xpry},{strike},{opt},"
        f"{o},{h},{low},{c},{c},{oi},{vol},999.0"
    )


def _udiff_csv(trad_dt: str, *, o: str, h: str, low: str, c: str) -> str:
    rows = [
        _UDIFF_HEADER,
        _udiff_row(trad_dt=trad_dt, o=o, h=h, low=low, c=c),  # the contract under test
        _udiff_row(trad_dt=trad_dt, opt="PE", o="40", h="55", low="35", c="50"),  # wrong opt type
        _udiff_row(trad_dt=trad_dt, strike="22400", o="900", h="950", low="880", c="920"),  # strike
        _udiff_row(trad_dt=trad_dt, xpry="2026-09-15", o="70", h="80", low="60", c="75"),  # expiry
        _udiff_row(  # an index future on the same underlying/expiry -- blank OptnTp/StrkPric
            trad_dt=trad_dt,
            tckr="RELIANCE",
            xpry="2026-09-24",
            strike="",
            opt="",
            fin_tp="STF",
            o="1400",
            h="1420",
            low="1390",
            c="1410",
            oi="5000",
            vol="800",
        ),
    ]
    return "\n".join(rows) + "\n"


_LEGACY_HEADER = (
    "INSTRUMENT,SYMBOL,EXPIRY_DT,STRIKE_PR,OPTION_TYP,OPEN,HIGH,LOW,CLOSE,"
    "SETTLE_PR,CONTRACTS,VAL_INLAKH,OPEN_INT,CHG_IN_OI,TIMESTAMP"
)


def _legacy_csv() -> str:
    rows = [
        _LEGACY_HEADER,
        "OPTIDX,NIFTY,27-Jun-2024,24000,CE,120.5,140,110,135,134,5000,600,180000,1000,03-Jun-2024",
        "OPTIDX,NIFTY,27-Jun-2024,24000,PE,80,90,70,75,74,4000,300,90000,-500,03-Jun-2024",
    ]
    return "\n".join(rows) + "\n"


def _zip_bytes(inner_name: str, csv_text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(inner_name, csv_text)
    return buf.getvalue()


class _Handler:
    """Serves the two UDiFF day-files and one legacy day-file; 404 for anything else. Counts
    hits per path so a test can prove the on-disk cache stops a second download."""

    def __init__(self) -> None:
        self.hits: dict[str, int] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.hits[path] = self.hits.get(path, 0) + 1
        if "BhavCopy_NSE_FO_0_0_0_20260901" in path:
            return httpx.Response(
                200,
                content=_zip_bytes(
                    "d1.csv", _udiff_csv("2026-09-01", o="1500", h="1560", low="1490", c="1520")
                ),
            )
        if "BhavCopy_NSE_FO_0_0_0_20260902" in path:
            return httpx.Response(
                200,
                content=_zip_bytes(
                    "d2.csv", _udiff_csv("2026-09-02", o="1525", h="1600", low="1500", c="1580")
                ),
            )
        if "fo03JUN2024bhav" in path:
            return httpx.Response(200, content=_zip_bytes("legacy.csv", _legacy_csv()))
        return httpx.Response(404)


def _provider(tmp_path: Path, handler: httpx.MockTransport | _Handler) -> NseFoBhavcopyProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    return NseFoBhavcopyProvider(cache_dir=tmp_path, client=client)


# -- parse_fo_symbol --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [
        ("NIFTY 22300 CE 08 SEP 26", ("NIFTY", date(2026, 9, 8), "CE", 22300.0)),
        ("BANKNIFTY 52000 PE 30 SEP 26", ("BANKNIFTY", date(2026, 9, 30), "PE", 52000.0)),
        ("M&M 1400 CE 24 SEP 26", ("M&M", date(2026, 9, 24), "CE", 1400.0)),
        ("TCS FUT 29 SEP 26", ("TCS", date(2026, 9, 29), None, None)),
        ("IDEA 8.5 CE 24 SEP 26", ("IDEA", date(2026, 9, 24), "CE", 8.5)),
    ],
)
def test_parse_fo_symbol_accepts_real_contract_shapes(symbol, expected):
    contract = parse_fo_symbol(symbol)
    assert contract is not None
    assert (contract.underlying, contract.expiry, contract.option_type, contract.strike) == expected


@pytest.mark.parametrize("symbol", ["RELIANCE", "^NSEI", "NIFTY", "NIFTY 22300 XX 08 SEP 26", ""])
def test_parse_fo_symbol_rejects_non_fo_symbols(symbol):
    assert parse_fo_symbol(symbol) is None


# -- get_historical_data --------------------------------------------------------------------


def test_parses_an_option_contract_across_two_trading_days(tmp_path):
    provider = _provider(tmp_path, _Handler())
    candles = provider.get_historical_data(
        instrument_key="NSE_FO|40679",
        symbol="NIFTY 22300 CE 08 SEP 26",
        start=date(2026, 9, 1),
        end=date(2026, 9, 2),
        timeframe="1d",
    )
    assert [c.timestamp.date() for c in candles] == [date(2026, 9, 1), date(2026, 9, 2)]
    assert [c.close for c in candles] == [1520.0, 1580.0]
    assert candles[0].open_interest == 250000  # real OI from the bhavcopy, not a fabricated 0
    assert candles[0].volume == 12000
    assert candles[0].provider == "nse_fo_bhavcopy"
    assert candles[0].symbol == "NIFTY 22300 CE 08 SEP 26"


def test_filters_to_the_exact_strike_expiry_and_option_type(tmp_path):
    """The day-file also carries a PE, a different strike and a different expiry for the same
    underlying -- none of those noise rows must leak into the result."""
    provider = _provider(tmp_path, _Handler())
    candles = provider.get_historical_data(
        instrument_key="NSE_FO|40679",
        symbol="NIFTY 22300 CE 08 SEP 26",
        start=date(2026, 9, 1),
        end=date(2026, 9, 1),
        timeframe="1d",
    )
    assert len(candles) == 1
    assert candles[0].close == 1520.0  # the CE/22300/08-SEP row, not the 1/2/3 noise closes


def test_a_futures_symbol_matches_the_blank_optiontype_row(tmp_path):
    provider = _provider(tmp_path, _Handler())
    candles = provider.get_historical_data(
        instrument_key="NSE_FO|55555",
        symbol="RELIANCE FUT 24 SEP 26",
        start=date(2026, 9, 1),
        end=date(2026, 9, 1),
        timeframe="1d",
    )
    assert len(candles) == 1
    assert candles[0].close == 1410.0
    assert candles[0].open_interest == 5000


def test_intraday_timeframe_is_unsupported(tmp_path):
    provider = _provider(tmp_path, _Handler())
    with pytest.raises(ProviderUnsupportedIntervalError):
        provider.get_historical_data(
            instrument_key="NSE_FO|40679",
            symbol="NIFTY 22300 CE 08 SEP 26",
            start=date(2026, 9, 1),
            end=date(2026, 9, 1),
            timeframe="5m",
        )


def test_a_non_fo_symbol_raises_instrument_not_found(tmp_path):
    provider = _provider(tmp_path, _Handler())
    with pytest.raises(ProviderInstrumentNotFoundError):
        provider.get_historical_data(
            instrument_key="NSE_EQ|INE002A01018",
            symbol="RELIANCE",
            start=date(2026, 9, 1),
            end=date(2026, 9, 1),
            timeframe="1d",
        )


def test_no_matching_contract_in_the_window_raises_empty_data(tmp_path):
    provider = _provider(tmp_path, _Handler())
    with pytest.raises(ProviderEmptyDataError):
        provider.get_historical_data(
            instrument_key="NSE_FO|99999",
            symbol="NIFTY 99999 CE 08 SEP 26",
            start=date(2026, 9, 1),
            end=date(2026, 9, 2),
            timeframe="1d",
        )


def test_a_404_day_is_skipped_not_fatal(tmp_path):
    """Legacy window: 2024-06-03 has a file, 2024-06-04 returns 404 (a movable holiday the
    calendar doesn't know). The result is the one real day, not a hard failure."""
    provider = _provider(tmp_path, _Handler())
    candles = provider.get_historical_data(
        instrument_key="NSE_FO|1",
        symbol="NIFTY 24000 CE 27 JUN 24",
        start=date(2024, 6, 3),
        end=date(2024, 6, 4),
        timeframe="1d",
    )
    assert [c.timestamp.date() for c in candles] == [date(2024, 6, 3)]
    assert candles[0].close == 135.0
    assert candles[0].open_interest == 180000


def test_parses_the_legacy_pre_udiff_format(tmp_path):
    provider = _provider(tmp_path, _Handler())
    candles = provider.get_historical_data(
        instrument_key="NSE_FO|1",
        symbol="NIFTY 24000 CE 27 JUN 24",
        start=date(2024, 6, 3),
        end=date(2024, 6, 3),
        timeframe="1d",
    )
    assert len(candles) == 1
    assert (candles[0].open, candles[0].high, candles[0].low, candles[0].close) == (
        120.5,
        140.0,
        110.0,
        135.0,
    )


def test_day_files_are_cached_after_the_first_fetch(tmp_path):
    handler = _Handler()
    provider = _provider(tmp_path, handler)
    for _ in range(3):
        provider.get_historical_data(
            instrument_key="NSE_FO|40679",
            symbol="NIFTY 22300 CE 08 SEP 26",
            start=date(2026, 9, 1),
            end=date(2026, 9, 1),
            timeframe="1d",
        )
    downloaded = [p for p in handler.hits if "20260901" in p]
    assert sum(handler.hits[p] for p in downloaded) == 1  # downloaded once, then served from disk
    assert (tmp_path / "fo_20260901.csv").exists()


def test_a_404_day_is_cached_so_nse_is_not_re_hit(tmp_path):
    handler = _Handler()
    provider = _provider(tmp_path, handler)
    for _ in range(3):
        with contextlib.suppress(ProviderEmptyDataError):
            provider.get_historical_data(
                instrument_key="NSE_FO|1",
                symbol="NIFTY 24000 CE 27 JUN 24",
                start=date(2024, 6, 4),
                end=date(2024, 6, 4),
                timeframe="1d",
            )
    missing = [p for p in handler.hits if "fo04JUN2024bhav" in p]
    assert sum(handler.hits[p] for p in missing) == 1  # the 404 marker file stops repeat calls


def test_health_check_is_optimistic(tmp_path):
    assert _provider(tmp_path, _Handler()).health_check() is True


def test_the_scan_window_is_clamped_to_roughly_the_contract_lifetime(tmp_path):
    """A 2-year backfill request for a Sept-2026 contract must not fan out to 2024 day-files --
    those are all pre-listing 404s, and scanning them one at a time is what blew past the
    frontend's 120s on-demand-ingest poll (the "Timed out fetching real historical data"
    report). The scan is clamped to ~400 days before expiry."""
    handler = _Handler()
    provider = _provider(tmp_path, handler)
    provider.get_historical_data(
        instrument_key="NSE_FO|40679",
        symbol="NIFTY 22300 CE 08 SEP 26",  # expiry 2026-09-08
        start=date(2024, 9, 1),  # ~2 years before expiry
        end=date(2026, 9, 2),
        timeframe="1d",
    )
    requested = sorted(
        _re.search(r"_FO_0_0_0_(\d{8})_", path).group(1)  # type: ignore[union-attr]
        for path in handler.hits
        if "BhavCopy_NSE_FO" in path
    )
    assert requested, "expected at least one day-file request"
    assert requested[0] >= "20250801", f"scan reached back to {requested[0]} -- clamp not applied"


def test_day_files_are_fetched_concurrently(tmp_path):
    """The loader fans day-file downloads across a thread pool -- a slow-per-request handler for
    a multi-day window must finish in far less than sum(per-request latency)."""

    def slow_handler(request: httpx.Request) -> httpx.Response:
        _time.sleep(0.3)
        match = _re.search(r"_FO_0_0_0_(\d{8})_", request.url.path)
        if match and match.group(1).startswith("202609"):
            ymd = match.group(1)
            trad = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}"
            return httpx.Response(
                200,
                content=_zip_bytes("d.csv", _udiff_csv(trad, o="10", h="12", low="9", c="11")),
            )
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(slow_handler), follow_redirects=True)
    provider = NseFoBhavcopyProvider(cache_dir=tmp_path, client=client)
    start = _time.perf_counter()
    candles = provider.get_historical_data(
        instrument_key="NSE_FO|1",
        symbol="NIFTY 22300 CE 08 SEP 26",
        start=date(2026, 9, 1),
        end=date(2026, 9, 8),
        timeframe="1d",
    )
    elapsed = _time.perf_counter() - start
    assert len(candles) == 6  # Sep 1-8 2026 minus the weekend
    assert elapsed < 6 * 0.3, f"{elapsed:.2f}s for 6 x 0.3s requests -- not run concurrently"
