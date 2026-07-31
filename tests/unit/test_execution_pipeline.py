"""LiveExecutionPipeline tests (Phase 4 Epic E4.2), per Phase_6_Trading_Engine_Design.md §5:
tick -> indicator update -> signal -> risk check -> broker routing.

test_nfr02_per_tick_latency_stays_under_50ms_at_p95 below measures the pipeline's own logic
against a `FakeBrokerAdapter` (in-memory, no network) -- fast and deterministic, good for
catching a regression in the pipeline's own code, but it does NOT prove the <50ms budget holds
against a real broker. That real-broker proof lives in
tests/integration/test_nfr02_real_broker_latency.py, against Upstox's genuine sandbox.
"""

import time
from datetime import UTC, datetime

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
from src.engine.live.execution_pipeline import (
    LiveExecutionPipeline,
    RiskRejected,
    SymbolState,
    Tick,
    TradeSignal,
)
from src.engine.risk.kill_switch import MaxDrawdownKillSwitch
from src.engine.risk.ws_latency_guard import WebSocketLatencyGuard


class FakeBrokerAdapter(BrokerAdapter):
    def __init__(self) -> None:
        self.placed_orders: list[OrderRequest] = []

    async def place_order(self, order: OrderRequest) -> OrderResponse:
        self.placed_orders.append(order)
        return OrderResponse(
            broker_order_id=f"ORD{len(self.placed_orders)}",
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


def _tick(symbol: str = "RELIANCE", price: float = 2500.0) -> Tick:
    return Tick(symbol=symbol, price=price, timestamp=datetime.now(UTC))


def test_symbol_state_sma_needs_the_full_window():
    state = SymbolState(symbol="RELIANCE")
    state.update(100.0)
    state.update(102.0)

    assert state.sma(3) is None  # only 2 ticks so far
    state.update(104.0)
    assert state.sma(3) == pytest.approx(102.0)


def test_symbol_state_history_is_bounded():
    state = SymbolState(symbol="RELIANCE", max_history=5)
    for price in range(10):
        state.update(float(price))

    assert len(state.prices) == 5
    assert list(state.prices) == [5.0, 6.0, 7.0, 8.0, 9.0]


@pytest.mark.asyncio
async def test_handle_tick_returns_none_when_no_signal_fires():
    def never_signal(state: SymbolState) -> TradeSignal | None:
        return None

    broker = FakeBrokerAdapter()
    pipeline = LiveExecutionPipeline(
        broker=broker, signal_generator=never_signal, kill_switch=MaxDrawdownKillSwitch()
    )

    result = await pipeline.handle_tick(_tick())

    assert result is None
    assert broker.placed_orders == []


@pytest.mark.asyncio
async def test_handle_tick_routes_a_signal_to_the_broker():
    def always_buy(state: SymbolState) -> TradeSignal | None:
        return TradeSignal(symbol=state.symbol, side="BUY", quantity=1)

    broker = FakeBrokerAdapter()
    pipeline = LiveExecutionPipeline(
        broker=broker, signal_generator=always_buy, kill_switch=MaxDrawdownKillSwitch()
    )

    result = await pipeline.handle_tick(_tick())

    assert result is not None
    assert result.broker_order_id == "ORD1"
    assert len(broker.placed_orders) == 1
    assert broker.placed_orders[0].side == "BUY"


@pytest.mark.asyncio
async def test_handle_tick_updates_indicator_state_before_generating_a_signal():
    seen_prices: list[float] = []

    def record_and_skip(state: SymbolState) -> TradeSignal | None:
        seen_prices.append(state.prices[-1])
        return None

    broker = FakeBrokerAdapter()
    pipeline = LiveExecutionPipeline(
        broker=broker, signal_generator=record_and_skip, kill_switch=MaxDrawdownKillSwitch()
    )

    await pipeline.handle_tick(_tick(price=101.0))
    await pipeline.handle_tick(_tick(price=102.5))

    assert seen_prices == [101.0, 102.5]


@pytest.mark.asyncio
async def test_kill_switch_triggered_rejects_the_signal_before_it_reaches_the_broker():
    def always_buy(state: SymbolState) -> TradeSignal | None:
        return TradeSignal(symbol=state.symbol, side="BUY", quantity=1)

    kill_switch = MaxDrawdownKillSwitch()
    kill_switch.trip()
    broker = FakeBrokerAdapter()
    pipeline = LiveExecutionPipeline(
        broker=broker, signal_generator=always_buy, kill_switch=kill_switch
    )

    with pytest.raises(RiskRejected):
        await pipeline.handle_tick(_tick())

    assert broker.placed_orders == []  # never reached the broker


@pytest.mark.asyncio
async def test_a_pre_trade_check_can_veto_a_signal():
    def always_buy(state: SymbolState) -> TradeSignal | None:
        return TradeSignal(symbol=state.symbol, side="BUY", quantity=1)

    def reject_everything(signal: TradeSignal) -> None:
        raise RiskRejected(f"blocked {signal.symbol}")

    broker = FakeBrokerAdapter()
    pipeline = LiveExecutionPipeline(
        broker=broker,
        signal_generator=always_buy,
        kill_switch=MaxDrawdownKillSwitch(),
        pre_trade_checks=[reject_everything],
    )

    with pytest.raises(RiskRejected):
        await pipeline.handle_tick(_tick())

    assert broker.placed_orders == []


@pytest.mark.asyncio
async def test_separate_symbols_get_independent_state():
    def always_buy(state: SymbolState) -> TradeSignal | None:
        return TradeSignal(symbol=state.symbol, side="BUY", quantity=1)

    broker = FakeBrokerAdapter()
    pipeline = LiveExecutionPipeline(
        broker=broker, signal_generator=always_buy, kill_switch=MaxDrawdownKillSwitch()
    )

    await pipeline.handle_tick(_tick(symbol="RELIANCE", price=2500.0))
    await pipeline.handle_tick(_tick(symbol="TCS", price=3500.0))

    assert list(pipeline.state_for("RELIANCE").prices) == [2500.0]
    assert list(pipeline.state_for("TCS").prices) == [3500.0]


@pytest.mark.asyncio
async def test_nfr02_per_tick_latency_stays_under_50ms_at_p95():
    """Pipeline-only latency against a stubbed broker -- see
    tests/integration/test_nfr02_real_broker_latency.py for the real-broker counterpart."""

    def always_buy(state: SymbolState) -> TradeSignal | None:
        return TradeSignal(symbol=state.symbol, side="BUY", quantity=1)

    broker = FakeBrokerAdapter()
    pipeline = LiveExecutionPipeline(
        broker=broker, signal_generator=always_buy, kill_switch=MaxDrawdownKillSwitch()
    )

    n = 200
    durations = []
    for i in range(n):
        start = time.perf_counter()
        await pipeline.handle_tick(_tick(price=2500.0 + i))
        durations.append(time.perf_counter() - start)

    durations.sort()
    p95 = durations[int(n * 0.95)]
    assert p95 < 0.05, f"NFR-02 violated: p95 per-tick latency was {p95 * 1000:.2f}ms (limit 50ms)"


@pytest.mark.asyncio
async def test_a_paused_latency_guard_rejects_the_signal_before_it_reaches_the_broker():
    def always_buy(state: SymbolState) -> TradeSignal | None:
        return TradeSignal(symbol=state.symbol, side="BUY", quantity=1)

    latency_guard = WebSocketLatencyGuard(threshold_seconds=0.1)
    latency_guard.record(0.3)  # simulate a breach
    broker = FakeBrokerAdapter()
    pipeline = LiveExecutionPipeline(
        broker=broker,
        signal_generator=always_buy,
        kill_switch=MaxDrawdownKillSwitch(),
        latency_guard=latency_guard,
    )

    with pytest.raises(RiskRejected):
        await pipeline.handle_tick(_tick())

    assert broker.placed_orders == []


@pytest.mark.asyncio
async def test_trading_resumes_automatically_once_the_latency_guard_recovers():
    def always_buy(state: SymbolState) -> TradeSignal | None:
        return TradeSignal(symbol=state.symbol, side="BUY", quantity=1)

    latency_guard = WebSocketLatencyGuard(threshold_seconds=0.1)
    latency_guard.record(0.3)
    broker = FakeBrokerAdapter()
    pipeline = LiveExecutionPipeline(
        broker=broker,
        signal_generator=always_buy,
        kill_switch=MaxDrawdownKillSwitch(),
        latency_guard=latency_guard,
    )

    with pytest.raises(RiskRejected):
        await pipeline.handle_tick(_tick())

    latency_guard.record(0.01)  # feed has synced back up -- no manual reset needed
    result = await pipeline.handle_tick(_tick())

    assert result is not None
    assert len(broker.placed_orders) == 1
