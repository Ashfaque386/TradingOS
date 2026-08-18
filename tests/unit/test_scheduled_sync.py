"""REL-072 (Phase 3): src/data/ingest/scheduled_sync.py. External dependencies (Upstox/yfinance
provider calls, the instrument-master file download, the Parquet writer, the data lake) are
mocked; the real Postgres is used for the `Strategy.universe` union query, matching this
codebase's own established convention of mocking only the external I/O boundary.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete

from src.core.db import get_session
from src.data.ingest import scheduled_sync
from src.data.ingest.scheduled_sync import INITIAL_BACKFILL_DAYS, run_incremental_ingestion
from src.data.provenance import get_provenance
from src.data.providers.base import Candle, DataQualityReport
from src.data.providers.manager import MarketDataResult, MarketDataUnavailable
from src.models.account import Account
from src.models.market_data_provenance import MarketDataProvenance
from src.models.strategy import Strategy
from src.models.user import User

_TODAY = date(2026, 8, 18)


class _FakeDataLake:
    def __init__(self, symbols: list[str], latest_dates: dict[str, date | None]) -> None:
        self._symbols = symbols
        self._latest_dates = latest_dates

    def list_symbols(self) -> list[str]:
        return self._symbols

    def latest_date(self, symbol: str) -> date | None:
        return self._latest_dates.get(symbol)


class _FakeWriter:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.written: list[int] = []

    def write(self, df: object) -> int:
        rows = df.height  # type: ignore[attr-defined]
        self.written.append(rows)
        return rows


class _FakeInstrumentSyncService:
    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def sync(self, session: object, exchange: str) -> int:
        return 7


class _FakeManager:
    def __init__(self, results: dict[str, MarketDataResult], failures: set[str]) -> None:
        self.results = results
        self.failures = failures
        self.calls: list[tuple[str, date, date]] = []

    def get_historical_data(
        self, *, instrument_key: str, symbol: str, start: date, end: date, timeframe: str
    ) -> MarketDataResult:
        self.calls.append((symbol, start, end))
        if symbol in self.failures:
            raise MarketDataUnavailable("boom", errors={"upstox_v3": "boom"})
        return self.results[symbol]


def _candle(symbol: str, d: date) -> Candle:
    return Candle(
        timestamp=datetime(d.year, d.month, d.day, tzinfo=UTC),
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=1000,
        open_interest=None,
        instrument_key=f"NSE_EQ|{symbol}",
        symbol=symbol,
        timeframe="1d",
        provider="upstox_v3",
    )


def _result(symbol: str, *candle_dates: date) -> MarketDataResult:
    return MarketDataResult(
        candles=[_candle(symbol, d) for d in candle_dates],
        provider_requested="upstox_v3",
        provider_used="upstox_v3",
        retrieved_at=datetime.now(UTC),
        quality=DataQualityReport(valid=True),
    )


@pytest.fixture
def _seed_strategy():
    """A real Strategy row with a unique test-only universe symbol, so
    `_target_symbols`'s real Strategy.universe union query has something real to find without
    depending on (or disturbing) whatever real strategies already exist in this dev DB."""
    suffix = uuid.uuid4().hex[:8].upper()
    user_id, account_id, strategy_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    universe_symbol = f"SCHEDTEST{suffix}"
    with get_session() as session:
        session.add(
            User(
                id=user_id,
                email=f"scheduled-sync-test-{user_id}@example.invalid",
                hashed_password="x",
                role="Trader",
            )
        )
        session.commit()
    with get_session() as session:
        session.add(
            Account(
                id=account_id,
                user_id=user_id,
                broker="Zerodha",
                account_type="Paper",
                capital_allocated=Decimal("100000.00"),
            )
        )
        session.commit()
    with get_session() as session:
        session.add(
            Strategy(
                id=strategy_id,
                account_id=account_id,
                name=f"scheduled-sync-test-{suffix}",
                hypothesis="test",
                asset_class="Equity",
                style="Intraday",
                status="Ideation",
                max_drawdown_limit=Decimal("15.00"),
                universe=[universe_symbol],
            )
        )
        session.commit()

    yield universe_symbol

    with get_session() as session:
        session.query(Strategy).filter(Strategy.id == strategy_id).delete()
        session.query(Account).filter(Account.id == account_id).delete()
        session.query(User).filter(User.id == user_id).delete()
        session.commit()


def _patch_today(monkeypatch: pytest.MonkeyPatch, today: date) -> None:
    # scheduled_sync imports `date` directly (`from datetime import date`), so `date.today()`
    # inside run_incremental_ingestion resolves through that name -- patch it to a real `date`
    # subclass whose `today()` returns a fixed value, so window-math assertions are deterministic
    # regardless of what day the test suite actually runs on.
    monkeypatch.setattr(
        scheduled_sync, "date", type("date", (date,), {"today": staticmethod(lambda: today)})
    )


def test_target_symbols_unions_lake_symbols_and_strategy_universes(_seed_strategy):
    universe_symbol = _seed_strategy
    lake = _FakeDataLake(symbols=["RELIANCE"], latest_dates={})
    with get_session() as session:
        symbols = scheduled_sync._target_symbols(lake, session)
    assert "RELIANCE" in symbols
    assert universe_symbol in symbols


def test_run_incremental_ingestion_backfills_top_ups_skips_and_isolates_failures(
    monkeypatch: pytest.MonkeyPatch, _seed_strategy
):
    universe_symbol = _seed_strategy
    lake_symbols = ["EXISTING_TOPUP", "EXISTING_FRESH", "FAILING_PROVIDER", "UNRESOLVABLE"]
    latest_dates: dict[str, date | None] = {
        "EXISTING_TOPUP": _TODAY - timedelta(days=5),
        "EXISTING_FRESH": _TODAY,  # start would be _TODAY + 1 day -- already fresh, no fetch
        "FAILING_PROVIDER": _TODAY - timedelta(days=5),
        universe_symbol: None,  # never ingested -- a real backfill candidate
        "UNRESOLVABLE": None,
    }
    fake_lake = _FakeDataLake(symbols=lake_symbols, latest_dates=latest_dates)
    fake_writer = _FakeWriter()

    resolvable = {"EXISTING_TOPUP", "EXISTING_FRESH", "FAILING_PROVIDER", universe_symbol}

    def _fake_resolve(session: object, symbol: str, *, exchange: str = "NSE") -> str | None:
        return f"NSE_EQ|{symbol}" if symbol in resolvable else None

    manager = _FakeManager(
        results={
            "EXISTING_TOPUP": _result("EXISTING_TOPUP", _TODAY - timedelta(days=4)),
            universe_symbol: _result(universe_symbol, _TODAY - timedelta(days=1)),
        },
        failures={"FAILING_PROVIDER"},
    )

    monkeypatch.setattr(scheduled_sync, "DataLake", lambda root: fake_lake)
    monkeypatch.setattr(scheduled_sync, "ParquetLakeWriter", lambda root: fake_writer)
    monkeypatch.setattr(scheduled_sync, "InstrumentSyncService", _FakeInstrumentSyncService)
    monkeypatch.setattr(scheduled_sync, "resolve_instrument_key", _fake_resolve)
    monkeypatch.setattr(scheduled_sync, "build_market_data_manager", lambda: manager)
    _patch_today(monkeypatch, _TODAY)

    summary = run_incremental_ingestion()

    assert summary.instruments_synced == 7
    assert summary.symbols_topped_up == ["EXISTING_TOPUP"]
    assert summary.symbols_backfilled == [universe_symbol]
    assert "EXISTING_FRESH" in summary.symbols_already_fresh
    assert summary.symbols_failed == ["FAILING_PROVIDER"]
    assert "UNRESOLVABLE" in summary.symbols_skipped_unresolvable

    # EXISTING_FRESH's window (start > today) never even reaches the provider -- no wasted call.
    called_symbols = {c[0] for c in manager.calls}
    assert "EXISTING_FRESH" not in called_symbols

    topup_call = next(c for c in manager.calls if c[0] == "EXISTING_TOPUP")
    assert topup_call[1] == _TODAY - timedelta(days=4)  # latest_date + 1 day
    assert topup_call[2] == _TODAY

    backfill_call = next(c for c in manager.calls if c[0] == universe_symbol)
    assert backfill_call[1] == _TODAY - timedelta(days=INITIAL_BACKFILL_DAYS)
    assert backfill_call[2] == _TODAY

    # One symbol's real provider failure never stops the others from being processed.
    assert len(fake_writer.written) == 2  # EXISTING_TOPUP + the backfilled universe symbol

    # REL-073: a real provenance row lands for every successfully-processed symbol.
    try:
        with get_session() as session:
            topup_provenance = get_provenance(session, "EXISTING_TOPUP")
            assert topup_provenance is not None
            assert topup_provenance.provider == "upstox_v3"
            backfill_provenance = get_provenance(session, universe_symbol)
            assert backfill_provenance is not None
            assert backfill_provenance.provider == "upstox_v3"
    finally:
        with get_session() as session:
            session.execute(
                delete(MarketDataProvenance).where(
                    MarketDataProvenance.symbol.in_(["EXISTING_TOPUP", universe_symbol])
                )
            )
            session.commit()


def test_run_incremental_ingestion_survives_a_real_instrument_sync_failure(
    monkeypatch: pytest.MonkeyPatch, _seed_strategy
):
    universe_symbol = _seed_strategy
    fake_lake = _FakeDataLake(symbols=[], latest_dates={universe_symbol: _TODAY})
    fake_writer = _FakeWriter()

    class _BrokenInstrumentSyncService:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def sync(self, session: object, exchange: str) -> int:
            raise RuntimeError("real network failure downloading the instrument master")

    empty_manager = _FakeManager(results={}, failures=set())
    monkeypatch.setattr(scheduled_sync, "DataLake", lambda root: fake_lake)
    monkeypatch.setattr(scheduled_sync, "ParquetLakeWriter", lambda root: fake_writer)
    monkeypatch.setattr(scheduled_sync, "InstrumentSyncService", _BrokenInstrumentSyncService)
    monkeypatch.setattr(
        scheduled_sync, "resolve_instrument_key", lambda session, symbol, **kw: None
    )
    monkeypatch.setattr(scheduled_sync, "build_market_data_manager", lambda: empty_manager)
    _patch_today(monkeypatch, _TODAY)

    # A failed instrument-master sync must not crash the whole run -- the OHLCV top-up loop
    # still executes (here, resolving nothing, since resolve_instrument_key is stubbed to None).
    summary = run_incremental_ingestion()
    assert summary.instruments_synced == 0
    assert universe_symbol in summary.symbols_skipped_unresolvable
