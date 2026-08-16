"""REL-071 (Phase 2): src/data/instruments.py's read surface, against real seeded rows in the
real dev Postgres (matching this codebase's own DB-test convention -- see
tests/integration/test_market_data_router.py's seed/cleanup pattern). Uses a fake, dedicated
`provider`/`exchange` pair so these tests never collide with the real Upstox-synced rows already
present in this environment.
"""

from __future__ import annotations

from sqlalchemy import delete

from src.core.db import get_session
from src.data.instruments import get_equities, get_indices, resolve_instrument_key, search
from src.models.instrument import Instrument

_PROVIDER = "test_query_provider"
_EXCHANGE = "TESTQEX"


def _cleanup() -> None:
    with get_session() as session:
        session.execute(
            delete(Instrument).where(
                Instrument.provider == _PROVIDER, Instrument.exchange == _EXCHANGE
            )
        )
        session.commit()


def _seed() -> None:
    with get_session() as session:
        session.add_all(
            [
                Instrument(
                    provider=_PROVIDER,
                    instrument_key=f"{_EXCHANGE}_EQ|ALPHA",
                    exchange=_EXCHANGE,
                    segment=f"{_EXCHANGE}_EQ",
                    symbol="ALPHACORP",
                    name="Alpha Corp Ltd",
                    instrument_type="EQ",
                    isin="INE_ALPHA_01",
                    is_active=True,
                ),
                Instrument(
                    provider=_PROVIDER,
                    instrument_key=f"{_EXCHANGE}_EQ|BETA",
                    exchange=_EXCHANGE,
                    segment=f"{_EXCHANGE}_EQ",
                    symbol="BETACORP",
                    name="Beta Industries",
                    instrument_type="EQ",
                    isin="INE_BETA_01",
                    is_active=True,
                ),
                Instrument(
                    provider=_PROVIDER,
                    instrument_key=f"{_EXCHANGE}_INDEX|ALPHAIDX",
                    exchange=_EXCHANGE,
                    segment=f"{_EXCHANGE}_INDEX",
                    # Real finding this mirrors: Upstox's own Nifty 50 row has symbol="NIFTY"
                    # but name="Nifty 50" -- a query against `name` must still find it.
                    symbol="ALPHAIDX",
                    name="Alpha Weighted Index",
                    instrument_type="INDEX",
                    isin=None,
                    is_active=True,
                ),
                Instrument(
                    provider=_PROVIDER,
                    instrument_key=f"{_EXCHANGE}_EQ|DELISTED",
                    exchange=_EXCHANGE,
                    segment=f"{_EXCHANGE}_EQ",
                    symbol="GONECORP",
                    name="Gone Corp",
                    instrument_type="EQ",
                    isin="INE_GONE_01",
                    is_active=False,
                ),
            ]
        )
        session.commit()


def setup_function() -> None:
    _cleanup()
    _seed()


def teardown_function() -> None:
    _cleanup()


def test_search_matches_symbol_case_insensitively():
    with get_session() as session:
        rows, total = search(session, query="alphacorp", exchange=_EXCHANGE)
    assert total == 1
    assert rows[0].symbol == "ALPHACORP"


def test_search_matches_name_when_symbol_does_not_contain_the_query():
    # "Alpha Weighted Index" only matches via `name`, not `symbol` ("ALPHAIDX") -- proves the
    # real Nifty-50-style symbol != name gap this module was built to close.
    with get_session() as session:
        rows, total = search(session, query="Weighted", exchange=_EXCHANGE)
    assert total == 1
    assert rows[0].symbol == "ALPHAIDX"


def test_search_excludes_inactive_rows():
    with get_session() as session:
        rows, total = search(session, query="Gone", exchange=_EXCHANGE)
    assert total == 0
    assert rows == []


def test_search_filters_by_instrument_type():
    with get_session() as session:
        rows, total = search(session, exchange=_EXCHANGE, instrument_type="INDEX")
    assert total == 1
    assert rows[0].symbol == "ALPHAIDX"


def test_search_pagination_returns_the_real_total_count_alongside_the_page_slice():
    with get_session() as session:
        rows, total = search(session, exchange=_EXCHANGE, instrument_type="EQ", page=1, page_size=1)
    assert total == 2  # ALPHACORP + BETACORP are both active EQ rows
    assert len(rows) == 1


def test_get_equities_returns_only_active_eq_rows_sorted_by_symbol():
    with get_session() as session:
        rows = get_equities(session, _EXCHANGE)
    assert [r.symbol for r in rows] == ["ALPHACORP", "BETACORP"]


def test_get_indices_returns_only_active_index_rows():
    with get_session() as session:
        rows = get_indices(session, _EXCHANGE)
    assert [r.symbol for r in rows] == ["ALPHAIDX"]


def test_resolve_instrument_key_returns_the_real_key_for_an_exact_active_symbol():
    with get_session() as session:
        key = resolve_instrument_key(session, "ALPHACORP", exchange=_EXCHANGE)
    assert key == f"{_EXCHANGE}_EQ|ALPHA"


def test_resolve_instrument_key_returns_none_for_an_inactive_symbol():
    with get_session() as session:
        key = resolve_instrument_key(session, "GONECORP", exchange=_EXCHANGE)
    assert key is None


def test_resolve_instrument_key_returns_none_for_an_unknown_symbol():
    with get_session() as session:
        key = resolve_instrument_key(session, "NOSUCHSYMBOL", exchange=_EXCHANGE)
    assert key is None
