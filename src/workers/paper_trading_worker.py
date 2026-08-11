"""Layer 2's real running process (REL-034): genuinely wires up the tick-driven engine that has
existed, fully built and tested, since Phase 4 (`src/engine/live/execution_pipeline.py`) but was
never once instantiated anywhere in the running app -- confirmed by grep before this worker was
written. Mirrors `src/workers/tick_publisher.py`'s own standalone-process pattern (a real
separate compose service, not an in-process FastAPI task) -- see this worker's own compose
service comment in docker-compose.yml for why.

One `PaperExecutionPipeline` per currently-open paper position (across every `"PaperTrading"`-
status strategy), watching real live ticks for stop-loss exits and price-recovery re-entries
(src/engine/paper_trading/intraday_risk_rules.py). Pipelines are added when a new position opens
and removed only when its strategy leaves `"PaperTrading"` status entirely -- NEVER removed just
because the position closed (a stop-loss exit), since the pipeline's own internal state is what
tracks "flat, watching for re-entry." `pipelines_by_symbol` is mutated in place by the periodic
sync loop and read live by the one long-running `run_multi_symbol_tick_listener` task
(src/engine/live/tick_listener.py) -- no task restart needed when the pipeline set changes.
"""

import asyncio
import logging

from sqlalchemy import select

from src.brokers.factory import NoBrokerConfigured, build_broker
from src.core.db import get_session
from src.data.reference.market_hours import is_market_open
from src.engine.live.tick_listener import get_async_redis_client, run_multi_symbol_tick_listener
from src.engine.paper_trading.intraday_risk_rules import build_stop_loss_signal_generator
from src.engine.paper_trading.paper_account import get_paper_account
from src.engine.paper_trading.paper_execution_pipeline import PaperExecutionPipeline
from src.engine.paper_trading.paper_kill_switch import get_paper_kill_switch
from src.engine.paper_trading.position_accounting import replay_ledger
from src.models.paper_trading import PaperTrade
from src.models.strategy import Strategy

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("paper_trading_worker")

SYNC_INTERVAL_SECONDS = 60


async def _sync_pipelines(pipelines_by_symbol: dict[str, PaperExecutionPipeline]) -> None:
    try:
        broker = build_broker()
    except NoBrokerConfigured:
        logger.warning("No broker configured -- cannot open any intraday pipelines this cycle.")
        return

    with get_session() as session:
        account = get_paper_account(session)
        strategies = list(
            session.execute(select(Strategy).where(Strategy.status == "PaperTrading"))
            .scalars()
            .all()
        )

    active_symbols: set[str] = set()
    for strategy in strategies:
        if not strategy.universe or strategy.asset_class == "F&O":
            continue
        symbol = strategy.universe[0]
        active_symbols.add(symbol)
        if symbol in pipelines_by_symbol:
            continue  # already tracked -- preserve its open/flat re-entry state across cycles

        with get_session() as session:
            trades = list(
                session.execute(
                    select(PaperTrade)
                    .where(PaperTrade.strategy_id == strategy.id)
                    .order_by(PaperTrade.executed_at.asc())
                )
                .scalars()
                .all()
            )
        positions, _closes = replay_ledger(trades)
        pos = positions.get(symbol)
        if pos is None or pos.net_quantity <= 0:
            continue  # nothing open yet to protect intraday

        signal_generator = build_stop_loss_signal_generator(
            symbol=symbol,
            quantity=pos.net_quantity,
            entry_price=pos.average_cost,
            max_drawdown_limit_pct=float(strategy.max_drawdown_limit),
        )
        pipelines_by_symbol[symbol] = PaperExecutionPipeline(
            broker=broker,
            signal_generator=signal_generator,
            kill_switch=get_paper_kill_switch(),
            account_id=str(account.id),
            strategy_id=str(strategy.id),
        )
        logger.info(
            "Opened intraday pipeline: %s qty=%s entry=%s (strategy=%s)",
            symbol,
            pos.net_quantity,
            pos.average_cost,
            strategy.id,
        )

    for symbol in list(pipelines_by_symbol):
        if symbol not in active_symbols:
            del pipelines_by_symbol[symbol]
            logger.info("Closed intraday pipeline: %s (strategy no longer PaperTrading)", symbol)


async def main() -> None:
    logger.info(
        "Paper trading worker starting (REL-034) -- syncing intraday pipelines every %ss "
        "during real NSE market hours.",
        SYNC_INTERVAL_SECONDS,
    )
    pipelines_by_symbol: dict[str, PaperExecutionPipeline] = {}
    client = get_async_redis_client()
    listener_task = asyncio.create_task(run_multi_symbol_tick_listener(client, pipelines_by_symbol))
    try:
        while True:
            try:
                if is_market_open():
                    await _sync_pipelines(pipelines_by_symbol)
                elif pipelines_by_symbol:
                    # Outside market hours (or a real holiday) -- nothing should be watching
                    # ticks that shouldn't be firing anyway; a fresh sync next real session
                    # start rebuilds pipelines from that day's real open positions.
                    pipelines_by_symbol.clear()
                    logger.info("Market closed -- cleared all intraday pipelines.")
            except Exception as exc:  # noqa: BLE001 -- must never crash this standing loop
                logger.warning("Paper trading worker sync cycle failed (will retry): %s", exc)
            await asyncio.sleep(SYNC_INTERVAL_SECONDS)
    finally:
        listener_task.cancel()
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
