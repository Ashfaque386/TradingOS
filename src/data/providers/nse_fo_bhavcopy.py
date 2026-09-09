"""NSE F&O bhavcopy market-data provider (REL-091).

The one free, official, *complete* source of Indian F&O history. NSE publishes one
end-of-day bhavcopy per trading day covering **every** listed futures/options contract --
every strike, every expiry -- with OHLC, settlement price, traded volume and real open
interest. This closes the gap `UpstoxV3Provider` leaves (src/data/providers/upstox_v3.py):
Upstox's *active* Historical Candle Data V3 endpoint caps daily option history at ~1 year and
only serves currently-listed, reasonably-liquid strikes; expired contracts need Upstox's paid
"Plus" plan. `YahooFinanceProvider` has no NSE F&O at all.

`build_market_data_manager()` puts this provider **first** for F&O instruments (Upstox V3 stays
the fallback), and leaves the equity/index chain (Upstox V3 -> yfinance) untouched.

Source files -- immutable once published, so each day-file is cached on disk on first fetch:
  - UDiFF (>= 2024-07-08):
    https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv.zip
  - Legacy (< 2024-07-08):
    https://nsearchives.nseindia.com/content/historical/DERIVATIVES/YYYY/MON/foDDMONYYYYbhav.csv.zip

EOD only -- no intraday (that's Phase 2, Kite Connect). The current trading day's file appears
only after NSE publishes it (~7 pm IST); a request that includes today just gets every earlier
day it can until then.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import polars as pl
import structlog

from src.data.providers.base import (
    Candle,
    MarketDataProvider,
    ProviderEmptyDataError,
    ProviderInstrumentNotFoundError,
    ProviderInvalidDataError,
    ProviderNetworkError,
    ProviderUnsupportedIntervalError,
    Timeframe,
)
from src.data.reference.nse_holiday_calendar import trading_days_between

logger = structlog.get_logger(__name__)

_IST = ZoneInfo("Asia/Kolkata")
_ARCHIVE = "https://nsearchives.nseindia.com"
# NSE switched every bhavcopy to the UDiFF layout on this date (Circular 62424, 2024-06-12).
_UDIFF_START = date(2024, 7, 8)
_NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/csv,application/zip,*/*",
}
_MONTHS = {
    m: i
    for i, m in enumerate(
        ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"],
        start=1,
    )
}

# "<UNDERLYING> <STRIKE> <CE|PE> <DD> <MON> <YY>"  or  "<UNDERLYING> FUT <DD> <MON> <YY>"
# -- the exact `trading_symbol` shape instrument_sync.py synced for NSE F&O rows (REL-078/088).
_FO_SYMBOL_RE = re.compile(
    r"^(?P<underlying>[A-Z][A-Z0-9&\-]*)\s+"
    r"(?:(?P<strike>\d+(?:\.\d+)?)\s+(?P<opt>CE|PE)|FUT)\s+"
    r"(?P<day>\d{2})\s+(?P<mon>[A-Z]{3})\s+(?P<yy>\d{2})$"
)


@dataclass(frozen=True)
class FoContract:
    underlying: str
    expiry: date
    option_type: str | None  # "CE" / "PE" for an option; None for a future
    strike: float | None  # the strike for an option; None for a future


def parse_fo_symbol(symbol: str) -> FoContract | None:
    """`"NIFTY 22300 CE 08 SEP 26"` -> `FoContract(...)`; `None` for anything that isn't an NSE
    F&O contract symbol (a bare equity like `"RELIANCE"`, an index like `"^NSEI"`, ...). Shared
    with `MarketDataManager` so "is this an F&O instrument?" is decided in exactly one place."""
    match = _FO_SYMBOL_RE.match(symbol.strip())
    if match is None:
        return None
    month = _MONTHS.get(match["mon"])
    if month is None:
        return None
    try:
        expiry = date(2000 + int(match["yy"]), month, int(match["day"]))
    except ValueError:
        return None
    strike = float(match["strike"]) if match["strike"] else None
    return FoContract(match["underlying"], expiry, match["opt"], strike)


# UDiFF (current) vs legacy (< 2024-07-08) column names for the six fields we read.
_UDIFF_COLS = ("OpnPric", "HghPric", "LwPric", "ClsPric", "TtlTradgVol", "OpnIntrst")
_LEGACY_COLS = ("OPEN", "HIGH", "LOW", "CLOSE", "CONTRACTS", "OPEN_INT")


class NseFoBhavcopyProvider(MarketDataProvider):
    name = "nse_fo_bhavcopy"

    def __init__(
        self,
        *,
        cache_dir: Path,
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._cache_dir = Path(cache_dir)
        self._client = client or httpx.Client(
            headers=_NSE_HEADERS, timeout=timeout, follow_redirects=True
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> NseFoBhavcopyProvider:
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
        if timeframe != "1d":
            raise ProviderUnsupportedIntervalError(
                f"nse_fo_bhavcopy is an end-of-day source -- timeframe={timeframe!r} is not "
                "available (use Kite Connect for intraday F&O history)"
            )
        contract = parse_fo_symbol(symbol)
        if contract is None:
            raise ProviderInstrumentNotFoundError(
                f"nse_fo_bhavcopy: {symbol!r} is not an NSE F&O contract symbol"
            )

        candles: list[Candle] = []
        for day in trading_days_between(start, end):
            row = self._row_for_day(day, contract)
            if row is not None:
                candles.append(self._to_candle(row, day, instrument_key, symbol))

        if not candles:
            raise ProviderEmptyDataError(
                f"nse_fo_bhavcopy has no rows for {symbol} ({instrument_key}) {start}..{end}"
            )
        # trading_days_between() is ascending, so candles already are -- validate_candles()
        # (src/data/providers/base.py) never re-sorts on the caller's behalf.
        return candles

    def get_latest_data(self, *, instrument_key: str, symbol: str) -> Candle | None:
        contract = parse_fo_symbol(symbol)
        if contract is None:
            return None
        today = datetime.now(_IST).date()
        for day in reversed(trading_days_between(today - timedelta(days=10), today)):
            row = self._row_for_day(day, contract)
            if row is not None:
                return self._to_candle(row, day, instrument_key, symbol)
        return None

    def health_check(self) -> bool:
        """No cheap standalone endpoint exists (a real check would download a whole ~2-5 MB
        day-file). A genuine reachability failure surfaces from the real fetch as a
        `ProviderNetworkError`, which `MarketDataManager` retries then fails over on -- so this
        optimistically returns True rather than paying a full download just to prove liveness."""
        return True

    # -- internals ---------------------------------------------------------------------------

    def _row_for_day(self, day: date, contract: FoContract) -> dict[str, str] | None:
        frame = self._load_day(day)
        if frame is None:
            return None
        legacy = day < _UDIFF_START
        try:
            candidates = self._match_contract(frame, contract, legacy=legacy)
        except pl.exceptions.ColumnNotFoundError as exc:
            raise ProviderInvalidDataError(
                f"nse_fo_bhavcopy {day.isoformat()} file is missing an expected column: {exc}"
            ) from exc

        price_cols = _LEGACY_COLS if legacy else _UDIFF_COLS
        for candidate in candidates:
            if self._prices_are_sane(candidate, price_cols):
                return candidate
        return None

    @staticmethod
    def _match_contract(
        frame: pl.DataFrame, contract: FoContract, *, legacy: bool
    ) -> list[dict[str, str]]:
        sym_col, expiry_col, opt_col, strike_col = (
            ("SYMBOL", "EXPIRY_DT", "OPTION_TYP", "STRIKE_PR")
            if legacy
            else ("TckrSymb", "XpryDt", "OptnTp", "StrkPric")
        )
        expiry_text = (
            contract.expiry.strftime("%d-%b-%Y") if legacy else contract.expiry.isoformat()
        )
        filtered = frame.filter(
            (pl.col(sym_col).str.strip_chars().str.to_uppercase() == contract.underlying)
            & (pl.col(expiry_col).str.strip_chars().str.to_uppercase() == expiry_text.upper())
        )
        rows: list[dict[str, str]] = [
            {k: ("" if v is None else str(v)) for k, v in row.items()}
            for row in filtered.to_dicts()
        ]
        out: list[dict[str, str]] = []
        for row in rows:
            opt = row.get(opt_col, "").strip().upper()
            if contract.option_type is None:
                # A future: legacy marks these "XX", UDiFF leaves OptnTp blank.
                if opt in ("", "XX"):
                    out.append(row)
                continue
            if opt != contract.option_type:
                continue
            raw_strike = row.get(strike_col, "").strip()
            try:
                if abs(float(raw_strike) - float(contract.strike or 0.0)) < 0.5:
                    out.append(row)
            except ValueError:
                continue
        return out

    @staticmethod
    def _prices_are_sane(row: dict[str, str], price_cols: tuple[str, ...]) -> bool:
        o_col, h_col, l_col, c_col, _, _ = price_cols
        try:
            o = float(row[o_col])
            h = float(row[h_col])
            low = float(row[l_col])
            c = float(row[c_col])
        except (KeyError, ValueError):
            return False
        if min(o, h, low, c) <= 0.0:
            # A contract that did not trade that day -- no meaningful OHLC. Skipped, not an error.
            return False
        return h >= low and h >= o and h >= c and low <= o and low <= c

    def _to_candle(
        self, row: dict[str, str], day: date, instrument_key: str, symbol: str
    ) -> Candle:
        o_col, h_col, l_col, c_col, vol_col, oi_col = (
            _LEGACY_COLS if day < _UDIFF_START else _UDIFF_COLS
        )
        return Candle(
            timestamp=datetime.combine(day, time(0, 0), tzinfo=_IST),
            open=float(row[o_col]),
            high=float(row[h_col]),
            low=float(row[l_col]),
            close=float(row[c_col]),
            volume=int(float(row.get(vol_col, "0") or "0")),
            open_interest=int(float(row.get(oi_col, "0") or "0")),
            instrument_key=instrument_key,
            symbol=symbol,
            timeframe="1d",
            provider=self.name,
        )

    def _load_day(self, day: date) -> pl.DataFrame | None:
        cache_file = self._cache_dir / f"fo_{day:%Y%m%d}.csv"
        if cache_file.exists():
            text = cache_file.read_text(encoding="utf-8", errors="replace")
            return self._read_csv(text) if text.strip() else None

        url = self._url_for(day)
        try:
            response = self._client.get(url)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                # No file for this day (a movable holiday the calendar doesn't know, or a date
                # outside the archive's coverage). Cache an empty marker so we never re-ask NSE.
                self._write_cache(cache_file, "")
                logger.info("nse_fo_bhavcopy_no_file", day=day.isoformat())
                return None
            raise ProviderNetworkError(
                f"nse_fo_bhavcopy HTTP {exc.response.status_code} for {url}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderNetworkError(f"nse_fo_bhavcopy fetch failed for {url}: {exc}") from exc

        try:
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                names = archive.namelist()
                if not names:
                    raise ProviderInvalidDataError(f"nse_fo_bhavcopy: empty zip at {url}")
                csv_bytes = archive.read(names[0])
        except zipfile.BadZipFile as exc:
            raise ProviderInvalidDataError(
                f"nse_fo_bhavcopy: {url} did not return a valid zip ({exc})"
            ) from exc

        text = csv_bytes.decode("utf-8", errors="replace")
        self._write_cache(cache_file, text)
        return self._read_csv(text)

    @staticmethod
    def _url_for(day: date) -> str:
        if day >= _UDIFF_START:
            return f"{_ARCHIVE}/content/fo/BhavCopy_NSE_FO_0_0_0_{day:%Y%m%d}_F_0000.csv.zip"
        mon = day.strftime("%b").upper()
        return (
            f"{_ARCHIVE}/content/historical/DERIVATIVES/{day:%Y}/{mon}"
            f"/fo{day:%d}{mon}{day:%Y}bhav.csv.zip"
        )

    @staticmethod
    def _read_csv(text: str) -> pl.DataFrame:
        frame = pl.read_csv(io.StringIO(text), infer_schema_length=0, truncate_ragged_lines=True)
        return frame.rename({c: c.strip() for c in frame.columns})

    def _write_cache(self, cache_file: Path, text: str) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(text, encoding="utf-8")
