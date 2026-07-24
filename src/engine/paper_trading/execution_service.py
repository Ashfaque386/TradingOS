"""Paper Trading execution service (Phase 4 Epic E4.4): fetches a REAL Level-2 quote from
whichever broker is configured (src/brokers/factory.py, read-only, no funds at risk), simulates
the fill via src/engine/paper_trading/slippage_model.py's real depth-walking logic, and persists
the result to PAPER_TRADES (src/models/paper_trading.py) -- never calls place_order.
"""

from datetime import UTC, datetime

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
    strategy_id: str | None = None,
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
            strategy_id=strategy_id,
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
