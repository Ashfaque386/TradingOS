"""src/api/routers/agents.py's `_fetch_existing_portfolio_equity_curve` (Risk Manager correlation
blend) against the real Postgres `account_equity_snapshots` table (AccountEquitySnapshot, DB-035).

Uses far-future synthetic snapshot_dates (2099-xx-xx) so this test can never collide with real
snapshot rows the seeded Paper account accumulates over time via
src/engine/paper_trading/equity_snapshot.py::take_daily_snapshot() -- inserts and cleans up its
own rows only.
"""

from datetime import date
from decimal import Decimal

from src.api.routers.agents import _fetch_existing_portfolio_equity_curve
from src.core.db import get_session
from src.engine.paper_trading.paper_account import get_paper_account
from src.models.account import AccountEquitySnapshot

# (snapshot_date, equity) pairs, deliberately inserted out of date order below -- the assertion
# relies on _fetch_existing_portfolio_equity_curve's own ORDER BY snapshot_date, not insertion
# order, to come back sorted.
_SEEDED_ROWS = [
    (date(2099, 1, 3), 100500.0),
    (date(2099, 1, 1), 100000.0),
    (date(2099, 1, 2), 101000.0),
]


def _seed_snapshots() -> None:
    with get_session() as session:
        account_id = get_paper_account(session).id
        for snapshot_date, equity in _SEEDED_ROWS:
            session.add(
                AccountEquitySnapshot(
                    account_id=account_id,
                    snapshot_date=snapshot_date,
                    cash=Decimal("50000.00"),
                    realized_pnl_cumulative=Decimal("0.00"),
                    unrealized_pnl=Decimal("0.00"),
                    margin_blocked=Decimal("0.00"),
                    equity=Decimal(str(equity)),
                )
            )
        session.commit()


def _cleanup() -> None:
    with get_session() as session:
        account_id = get_paper_account(session).id
        session.query(AccountEquitySnapshot).filter(
            AccountEquitySnapshot.account_id == account_id,
            AccountEquitySnapshot.snapshot_date.in_([d for d, _ in _SEEDED_ROWS]),
        ).delete(synchronize_session=False)
        session.commit()


def test_fetch_existing_portfolio_equity_curve_returns_real_snapshots_in_date_order() -> None:
    _seed_snapshots()
    try:
        curve = _fetch_existing_portfolio_equity_curve()
    finally:
        _cleanup()

    seeded_dates = {d.isoformat() for d, _ in _SEEDED_ROWS}
    matching = [p for p in curve if p.date in seeded_dates]
    expected_sorted = sorted(_SEEDED_ROWS, key=lambda row: row[0])

    assert len(matching) == 3
    assert [p.date for p in matching] == [d.isoformat() for d, _ in expected_sorted]
    assert [p.equity for p in matching] == [equity for _, equity in expected_sorted]
