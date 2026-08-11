"""Live equity computation for the Paper Trading Account (REL-034).

Two layers, matching this ledger's "replay from the immutable trade log, no cached mutable
state" philosophy (src/engine/paper_trading/position_accounting.py) everywhere except the one
documented exception (AccountEquitySnapshot, for historical equity-curve queries only):

  - `compute_equity_from_positions` is pure/sync/testable: given the account's starting capital,
    its replayed positions, and already-fetched last prices for every open symbol, it returns
    equity = capital + cumulative realized P&L + mark-to-market unrealized P&L - margin blocked.
  - `compute_account_equity` is the async orchestrator real callers use: reads the Account row
    and its full PaperTrade ledger, replays it, fetches one real live quote per currently-open
    symbol (bounded -- the same on-demand real-quote pattern src/api/routers/portfolio.py
    already uses for the real account, not a new standing subscriber), and calls the pure
    function above. A quote fetch failing for one open symbol is a real, honest gap -- that
    symbol is simply excluded from unrealized P&L/margin for this call, not fabricated.
"""

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.brokers.base import BrokerAdapter
from src.engine.paper_trading.margin_model import compute_margin_summary
from src.engine.paper_trading.position_accounting import SymbolPosition, replay_ledger
from src.models.account import Account
from src.models.paper_trading import PaperTrade

logger = structlog.get_logger(__name__)


def compute_equity_from_positions(
    capital_allocated: float,
    positions: dict[str, SymbolPosition],
    last_prices: dict[str, float],
) -> float:
    realized = sum(p.realized_pnl for p in positions.values())
    unrealized = sum(
        (last_prices[symbol] - p.average_cost) * p.net_quantity
        for symbol, p in positions.items()
        if p.net_quantity != 0 and symbol in last_prices
    )
    margin_blocked = compute_margin_summary(positions, last_prices).total_margin_blocked
    return float(capital_allocated) + realized + unrealized - margin_blocked


async def compute_account_equity(account_id: str, session: Session, broker: BrokerAdapter) -> float:
    account = session.get(Account, account_id)
    if account is None:
        raise ValueError(f"No Account row for id={account_id}")

    trades = (
        session.execute(
            select(PaperTrade)
            .where(PaperTrade.account_id == account_id)
            .order_by(PaperTrade.executed_at.asc())
        )
        .scalars()
        .all()
    )
    positions, _closes = replay_ledger(list(trades))

    last_prices: dict[str, float] = {}
    for symbol, pos in positions.items():
        if pos.net_quantity == 0:
            continue
        try:
            quote = await broker.get_quote(symbol)
            last_prices[symbol] = quote.last_price
        except Exception as exc:  # noqa: BLE001 -- one symbol's failure must not stop the rest
            logger.warning("account_equity_quote_fetch_failed", symbol=symbol, error=str(exc))
            continue

    return compute_equity_from_positions(
        capital_allocated=float(account.capital_allocated),
        positions=positions,
        last_prices=last_prices,
    )
