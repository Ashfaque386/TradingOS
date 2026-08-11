"""Daily equity-snapshot job for the Paper Trading Account (REL-034).

Writes exactly one `AccountEquitySnapshot` row per real trading day -- a single forward pass
over the ledger via `compute_account_equity`/`margin_model`, not a replay per historical day.
See alembic/versions/c5d6e7f8a9b0's own docstring for why this one figure is cached at all,
unlike everything else in this ledger.
"""

from datetime import date

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.brokers.base import BrokerAdapter
from src.engine.paper_trading.account_equity import compute_account_equity
from src.engine.paper_trading.margin_model import compute_margin_summary
from src.engine.paper_trading.position_accounting import replay_ledger
from src.models.account import Account, AccountEquitySnapshot
from src.models.paper_trading import PaperTrade

logger = structlog.get_logger(__name__)


async def take_daily_snapshot(
    account_id: str, session: Session, broker: BrokerAdapter, *, as_of: date | None = None
) -> AccountEquitySnapshot | None:
    """Idempotent per (account_id, snapshot_date) -- re-running for a date that already has a
    row updates it in place rather than erroring or duplicating, so a retried/re-triggered job
    run is safe."""
    as_of = as_of or date.today()
    account = session.get(Account, account_id)
    if account is None:
        return None

    trades = list(
        session.execute(
            select(PaperTrade)
            .where(PaperTrade.account_id == account_id)
            .order_by(PaperTrade.executed_at.asc())
        )
        .scalars()
        .all()
    )
    positions, _closes = replay_ledger(trades)

    last_prices: dict[str, float] = {}
    for symbol, pos in positions.items():
        if pos.net_quantity == 0:
            continue
        try:
            quote = await broker.get_quote(symbol)
            last_prices[symbol] = quote.last_price
        except Exception as exc:  # noqa: BLE001 -- one symbol's failure must not stop the snapshot
            logger.warning("equity_snapshot_quote_fetch_failed", symbol=symbol, error=str(exc))
            continue

    realized_pnl_cumulative = sum(p.realized_pnl for p in positions.values())
    unrealized_pnl = sum(
        (last_prices[symbol] - p.average_cost) * p.net_quantity
        for symbol, p in positions.items()
        if p.net_quantity != 0 and symbol in last_prices
    )
    margin_blocked = compute_margin_summary(positions, last_prices).total_margin_blocked
    cash = float(account.capital_allocated) + realized_pnl_cumulative
    equity = await compute_account_equity(account_id, session, broker)

    existing = session.scalars(
        select(AccountEquitySnapshot).where(
            AccountEquitySnapshot.account_id == account_id,
            AccountEquitySnapshot.snapshot_date == as_of,
        )
    ).first()

    if existing is not None:
        existing.cash = cash
        existing.realized_pnl_cumulative = realized_pnl_cumulative
        existing.unrealized_pnl = unrealized_pnl
        existing.margin_blocked = margin_blocked
        existing.equity = equity
        snapshot = existing
    else:
        snapshot = AccountEquitySnapshot(
            account_id=account_id,
            snapshot_date=as_of,
            cash=cash,
            realized_pnl_cumulative=realized_pnl_cumulative,
            unrealized_pnl=unrealized_pnl,
            margin_blocked=margin_blocked,
            equity=equity,
        )
        session.add(snapshot)

    session.commit()
    session.refresh(snapshot)
    return snapshot
