"""Real Upstox instrument-master sync (REL-071, Phase 2 of the Upstox V3 + yfinance dual
market-data system). Closes Phase 1's own stated gap: `UpstoxV3Provider` needs a real
`instrument_key`, and nothing in this codebase could resolve a bare symbol into one until this
module populates `instruments` (src/models/instrument.py) from Upstox's own real data.

Real, confirmed mechanism (from Upstox's live developer docs, not invented): there is no live
instrument-search API -- the real, current source is a daily-refreshed (~6am IST) static gzipped
JSON file per exchange, a public, unauthenticated download (no token needed):
`https://assets.upstox.com/market-quote/instruments/exchange/{NSE|BSE}.json.gz`.

Real, confirmed per-type field schema: equities (`instrument_type="EQ"`) carry
`segment, name, exchange, isin, instrument_type, instrument_key, lot_size, tick_size,
trading_symbol`; indices (`instrument_type="INDEX"`) carry a minimal real set --
`segment, name, exchange, instrument_type, instrument_key, trading_symbol` -- genuinely no
ISIN/lot_size/tick_size, not an omission. Options (`CE`/`PE`) records are real too but out of
scope -- this codebase's own real options-chain browsing (REL-077) is served live from the
broker at query time (`BrokerAdapter.get_option_chain`), not from a local instrument catalog,
so there is no need to sync them here.

REL-078: futures (`instrument_type="FUT"`) are now in scope, closing this module's own prior
"F&O out of scope" boundary for that one type. Real, confirmed field schema (fetched from the
live file, not invented): `segment="NSE_FO", name, exchange, expiry (epoch ms),
instrument_type="FUT", underlying_symbol, instrument_key, lot_size, tick_size, trading_symbol
(e.g. "TCS FUT 29 SEP 26" -- a real, unique, human-readable string with the expiry already
baked in as text), strike_price` -- `strike_price` is always `0.0` for a real FUT row, never a
real strike, so it is not stored (`strike` stays `None`, the same honest-null convention already
used for EQ/INDEX).
"""

from __future__ import annotations

import argparse
import gzip
import json
from datetime import UTC, date, datetime
from typing import Any

import httpx
import structlog
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.core.db import get_session
from src.models.instrument import Instrument

logger = structlog.get_logger(__name__)

_INSTRUMENT_MASTER_URL = (
    "https://assets.upstox.com/market-quote/instruments/exchange/{exchange}.json.gz"
)
PROVIDER = "upstox_v3"
_SUPPORTED_INSTRUMENT_TYPES = {"EQ", "INDEX", "FUT"}


class InstrumentSyncService:
    def __init__(self, *, timeout: float = 30.0) -> None:
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> InstrumentSyncService:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def fetch_raw(self, exchange: str) -> list[dict[str, Any]]:
        """Downloads and gunzips the real, live Upstox instrument master file for `exchange`."""
        url = _INSTRUMENT_MASTER_URL.format(exchange=exchange)
        response = self._client.get(url)
        response.raise_for_status()
        decompressed = gzip.decompress(response.content)
        data: list[dict[str, Any]] = json.loads(decompressed)
        return data

    def sync(self, session: Session, exchange: str) -> int:
        """Real reactivate-then-upsert: every existing real `is_active` row for
        `(provider, exchange)` is marked inactive first, then each real supported row from the
        freshly-downloaded file is upserted with `is_active=True` -- an instrument absent from
        the fresh file (a real delisting) stays honestly inactive, never deleted. Returns the
        real count of rows upserted from this sync."""
        records = self.fetch_raw(exchange)

        session.execute(
            update(Instrument)
            .where(
                Instrument.provider == PROVIDER,
                Instrument.exchange == exchange,
                Instrument.is_active.is_(True),
            )
            .values(is_active=False)
        )

        written = 0
        for record in records:
            row = _parse_record(record, exchange=exchange)
            if row is None:
                continue
            stmt = insert(Instrument).values(provider=PROVIDER, is_active=True, **row)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_instruments_provider_key",
                set_={**row, "is_active": True},
            )
            session.execute(stmt)
            written += 1

        session.commit()
        logger.info("instrument_sync_complete", exchange=exchange, rows_written=written)
        return written


def _parse_record(record: dict[str, Any], *, exchange: str) -> dict[str, Any] | None:
    """Returns `None` for a real row this module doesn't ingest (options, or anything else
    outside `_SUPPORTED_INSTRUMENT_TYPES`) or a genuinely malformed record (missing a required
    real field) -- never a fabricated/partial row."""
    instrument_type = record.get("instrument_type")
    if instrument_type not in _SUPPORTED_INSTRUMENT_TYPES:
        return None

    instrument_key = record.get("instrument_key")
    symbol = record.get("trading_symbol")
    name = record.get("name")
    segment = record.get("segment")
    if not (instrument_key and symbol and name and segment):
        return None

    expiry_ms = record.get("expiry")
    expiry: date | None = (
        datetime.fromtimestamp(expiry_ms / 1000, tz=UTC).date()
        if instrument_type == "FUT" and expiry_ms
        else None  # unchanged for EQ/INDEX -- neither type carries a real expiry
    )

    return {
        "instrument_key": instrument_key,
        "exchange": exchange,
        "segment": segment,
        "symbol": symbol,
        "name": name,
        "instrument_type": instrument_type,
        "isin": record.get("isin"),
        "expiry": expiry,
        "strike": None,  # real for EQ/INDEX/FUT -- none of these carry a real strike (a real
        # FUT row's own strike_price is always 0.0, not a real value)
        "lot_size": record.get("lot_size"),
        "tick_size": record.get("tick_size"),
    }


def main() -> None:
    """CLI entrypoint (mirrors src/data/ingest/pipeline.py's own shape):
    `python -m src.data.ingest.instrument_sync --exchange NSE`. Not scheduled yet -- wiring this
    into a real APScheduler job (matching src/agents/scheduler.py's established pattern) is
    Phase 3's job."""
    parser = argparse.ArgumentParser(
        description="Sync the real Upstox instrument master into the TradingOS instruments table."
    )
    parser.add_argument("--exchange", choices=["NSE", "BSE"], default="NSE")
    args = parser.parse_args()

    with InstrumentSyncService() as service, get_session() as session:
        written = service.sync(session, args.exchange)
    print(f"Synced {written} real {args.exchange} instruments.")


if __name__ == "__main__":
    main()
