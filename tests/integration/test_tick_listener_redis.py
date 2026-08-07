"""Tick listener integration test against the real dockerized Redis service (Phase 4 Epic
E4.2): publishes a real tick over Redis pub/sub and confirms it flows all the way through
`run_tick_listener` -> `LiveExecutionPipeline.handle_tick()` -> broker routing.
"""

import asyncio
import json

import pytest

from src.brokers.base import (
    BrokerAdapter,
    Margin,
    OrderRequest,
    OrderResponse,
    OrderType,
    Position,
    Quote,
)
from src.engine.live.execution_pipeline import LiveExecutionPipeline, SymbolState, TradeSignal
from src.engine.live.tick_listener import get_async_redis_client, run_tick_listener
from src.engine.risk.kill_switch import MaxDrawdownKillSwitch
from src.memory.redis_client import TICK_CHANNEL_PREFIX


class RecordingBrokerAdapter(BrokerAdapter):
    def __init__(self) -> None:
        self.placed_orders: list[OrderRequest] = []

    async def place_order(self, order: OrderRequest) -> OrderResponse:
        self.placed_orders.append(order)
        return OrderResponse(
            broker_order_id="ORD1",
            status="OPEN",
            symbol=order.symbol,
            side=order.side,
            order_type=order.order_type,
            quantity=order.quantity,
        )

    async def modify_order(
        self,
        broker_order_id: str,
        *,
        quantity: int | None = None,
        order_type: OrderType | None = None,
        limit_price: float | None = None,
        trigger_price: float | None = None,
    ) -> OrderResponse:
        raise NotImplementedError

    async def cancel_order(self, broker_order_id: str) -> OrderResponse:
        raise NotImplementedError

    async def get_order_book(self) -> list[OrderResponse]:
        return []

    async def get_margin(self) -> Margin:
        return Margin(available_margin=0.0, used_margin=0.0)

    async def get_positions(self) -> list[Position]:
        return []

    async def get_quote(self, symbol: str) -> Quote:
        raise NotImplementedError

    async def get_option_chain(self, underlying: str, expiry):
        raise NotImplementedError

    async def list_expiries(self, underlying: str):
        raise NotImplementedError


@pytest.mark.asyncio
async def test_a_published_tick_flows_through_the_real_redis_listener_to_the_broker():
    def always_buy(state: SymbolState) -> TradeSignal | None:
        return TradeSignal(symbol=state.symbol, side="BUY", quantity=1)

    broker = RecordingBrokerAdapter()
    pipeline = LiveExecutionPipeline(
        broker=broker, signal_generator=always_buy, kill_switch=MaxDrawdownKillSwitch()
    )

    client = get_async_redis_client()
    listener_task = asyncio.create_task(run_tick_listener(client, pipeline))
    try:
        await asyncio.sleep(0.2)  # let the psubscribe land before publishing

        await client.publish(f"{TICK_CHANNEL_PREFIX}RELIANCE", json.dumps({"price": 2500.0}))

        for _ in range(50):  # poll up to ~1s for the async listener to process the message
            if broker.placed_orders:
                break
            await asyncio.sleep(0.02)
    finally:
        listener_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await listener_task
        await client.aclose()

    assert len(broker.placed_orders) == 1
    assert broker.placed_orders[0].symbol == "RELIANCE"
    assert list(pipeline.state_for("RELIANCE").prices) == [2500.0]
