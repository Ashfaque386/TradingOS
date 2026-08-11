"""src/engine/paper_trading/paper_execution_pipeline.py integration tests (REL-034), against
the real Postgres (a real PaperTrade row must actually be written) with a fake broker (no live
market dependency -- see the manual smoke test performed during implementation for confirmation
against a real broker/real quote).
"""

import uuid
from datetime import UTC, date, datetime

import pytest

from src.brokers.base import (
    BrokerAdapter,
    DepthLevel,
    Margin,
    OrderRequest,
    OrderResponse,
    Position,
    Quote,
)
from src.core.db import get_session
from src.engine.live.execution_pipeline import RiskRejected, SymbolState, Tick, TradeSignal
from src.engine.paper_trading.paper_account import get_paper_account
from src.engine.paper_trading.paper_execution_pipeline import PaperExecutionPipeline
from src.engine.risk.kill_switch import MaxDrawdownKillSwitch
from src.models.paper_trading import PaperTrade


class FakeBrokerAdapter(BrokerAdapter):
    async def place_order(self, order: OrderRequest) -> OrderResponse:
        raise AssertionError("PaperExecutionPipeline must never call place_order")

    async def modify_order(self, broker_order_id: str, **kwargs) -> OrderResponse:
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
        return Quote(
            symbol=symbol,
            last_price=1500.0,
            buy_depth=[DepthLevel(price=1499.5, quantity=100, orders=1)],
            sell_depth=[DepthLevel(price=1500.5, quantity=100, orders=1)],
        )

    async def get_option_chain(self, underlying: str, expiry: date):
        raise NotImplementedError

    async def list_expiries(self, underlying: str):
        raise NotImplementedError


def _tick(price: float = 1500.0) -> Tick:
    return Tick(symbol="INFY", price=price, timestamp=datetime.now(UTC))


def _cleanup(*trade_ids: uuid.UUID) -> None:
    with get_session() as session:
        for trade_id in trade_ids:
            session.query(PaperTrade).filter(PaperTrade.id == trade_id).delete()
        session.commit()


@pytest.mark.asyncio
async def test_a_fired_signal_writes_a_real_paper_trade_row_not_a_broker_order():
    with get_session() as session:
        account_id = str(get_paper_account(session).id)

    def always_buy(state: SymbolState) -> TradeSignal | None:
        return TradeSignal(symbol=state.symbol, side="BUY", quantity=10)

    pipeline = PaperExecutionPipeline(
        broker=FakeBrokerAdapter(),
        signal_generator=always_buy,
        kill_switch=MaxDrawdownKillSwitch(),
        account_id=account_id,
    )

    trade = await pipeline.handle_tick(_tick())
    try:
        assert trade is not None
        assert trade.symbol == "INFY"
        assert trade.side == "BUY"
        assert str(trade.account_id) == account_id

        with get_session() as session:
            row = session.get(PaperTrade, trade.id)
            assert row is not None
    finally:
        _cleanup(trade.id)


@pytest.mark.asyncio
async def test_no_signal_produces_no_trade():
    with get_session() as session:
        account_id = str(get_paper_account(session).id)

    def never_signal(state: SymbolState) -> TradeSignal | None:
        return None

    pipeline = PaperExecutionPipeline(
        broker=FakeBrokerAdapter(),
        signal_generator=never_signal,
        kill_switch=MaxDrawdownKillSwitch(),
        account_id=account_id,
    )

    result = await pipeline.handle_tick(_tick())
    assert result is None


@pytest.mark.asyncio
async def test_tripped_kill_switch_rejects_the_signal_before_any_trade_is_written():
    with get_session() as session:
        account_id = str(get_paper_account(session).id)

    def always_buy(state: SymbolState) -> TradeSignal | None:
        return TradeSignal(symbol=state.symbol, side="BUY", quantity=10)

    kill_switch = MaxDrawdownKillSwitch()
    kill_switch.trip()
    pipeline = PaperExecutionPipeline(
        broker=FakeBrokerAdapter(),
        signal_generator=always_buy,
        kill_switch=kill_switch,
        account_id=account_id,
    )

    with pytest.raises(RiskRejected):
        await pipeline.handle_tick(_tick())
