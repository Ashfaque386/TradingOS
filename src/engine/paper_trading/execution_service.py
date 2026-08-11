"""Paper Trading execution service (Phase 4 Epic E4.4): fetches a REAL Level-2 quote from
whichever broker is configured (src/brokers/factory.py, read-only, no funds at risk), simulates
the fill via src/engine/paper_trading/slippage_model.py's real depth-walking logic, and persists
the result to PAPER_TRADES (src/models/paper_trading.py) -- never calls place_order.

REL-034: every fill belongs to a real Account (`account_id`, required) -- see
src/engine/paper_trading/paper_account.py for how callers find the one seeded Paper account.
`instrument_type`/`underlying`/`strike`/`expiry` are populated for F&O fills (the daily signal
job and the intraday pipeline resolve each option leg to its own real tradable broker symbol
before calling this once per leg); they default to a plain EQUITY fill, matching every trade
this function has ever placed before this release.
"""

from datetime import UTC, date, datetime

from src.brokers.base import BrokerAdapter, Side
from src.core.db import get_session
from src.engine.paper_trading.slippage_model import simulate_fill
from src.models.paper_trading import PaperTrade


class NoLiquidityError(RuntimeError):
    """Raised when the real quote has no usable depth on the relevant side at all -- an honest
    failure, not a fabricated fill."""


async def execute_paper_trade(
    broker: BrokerAdapter,
    *,
    symbol: str,
    side: Side,
    quantity: int,
    account_id: str,
    strategy_id: str | None = None,
    instrument_type: str = "EQUITY",
    underlying: str | None = None,
    strike: float | None = None,
    expiry: date | None = None,
) -> PaperTrade:
    quote = await broker.get_quote(symbol)
    depth = quote.sell_depth if side == "BUY" else quote.buy_depth
    result = simulate_fill(side=side, quantity=quantity, depth=depth)

    if result.filled_quantity == 0:
        raise NoLiquidityError(
            f"No usable {'ask' if side == 'BUY' else 'bid'} depth for {symbol} -- nothing to fill"
        )

    with get_session() as session:
        trade = PaperTrade(
            account_id=account_id,
            strategy_id=strategy_id,
            instrument_type=instrument_type,
            underlying=underlying,
            strike=strike,
            expiry=expiry,
            symbol=symbol,
            side=side,
            requested_quantity=quantity,
            filled_quantity=result.filled_quantity,
            reference_price=quote.last_price,
            fill_price=result.average_fill_price,
            slippage_bps=result.slippage_bps,
            depth_snapshot={
                "buy": [level.model_dump() for level in quote.buy_depth],
                "sell": [level.model_dump() for level in quote.sell_depth],
                "fully_filled": result.fully_filled,
            },
            executed_at=datetime.now(UTC),
        )
        session.add(trade)
        session.commit()
        session.refresh(trade)
        return trade
