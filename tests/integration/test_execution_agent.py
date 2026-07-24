"""ExecutionAgent integration tests (Phase 4 Epic E4.2), against the real Postgres ORDERS
table (DB-008): order-state persistence, exponential backoff on broker timeouts, and the
partial-fill tracking sub-task, per Phase_4_AI_Agent_Design.md §10.
"""

import asyncio
import uuid
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from src.brokers.base import (
    BrokerAdapter,
    Margin,
    OrderRequest,
    OrderResponse,
    OrderType,
    Position,
    Quote,
)
from src.core.db import get_session
from src.engine.live.execution_agent import ExecutionAgent, ExecutionFailed
from src.models.account import Account
from src.models.strategy import Strategy
from src.models.trading import Order as OrderModel
from src.models.user import User


class ScriptedBrokerAdapter(BrokerAdapter):
    """`place_order_results`/`order_book_sequence` are consumed one entry at a time. An entry
    in `place_order_results` that's an Exception is raised instead of returned."""

    def __init__(
        self,
        place_order_results: list,
        order_book_sequence: list[list[OrderResponse]] | None = None,
    ) -> None:
        self._place_results = list(place_order_results)
        self._order_book_sequence = list(order_book_sequence or [])
        self.place_calls = 0
        self.order_book_calls = 0

    async def place_order(self, order: OrderRequest) -> OrderResponse:
        self.place_calls += 1
        result = self._place_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

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
        self.order_book_calls += 1
        if not self._order_book_sequence:
            return []
        if len(self._order_book_sequence) > 1:
            return self._order_book_sequence.pop(0)
        return self._order_book_sequence[0]  # hold on the last snapshot once exhausted

    async def get_margin(self) -> Margin:
        return Margin(available_margin=0.0, used_margin=0.0)

    async def get_positions(self) -> list[Position]:
        return []

    async def get_quote(self, symbol: str) -> Quote:
        raise NotImplementedError


def _response(
    broker_order_id: str = "ORD1", status: str = "OPEN", filled_quantity: int = 0
) -> OrderResponse:
    return OrderResponse(
        broker_order_id=broker_order_id,
        status=status,
        symbol="RELIANCE",
        side="BUY",
        order_type="MARKET",
        quantity=10,
        filled_quantity=filled_quantity,
    )


def _order() -> OrderRequest:
    return OrderRequest(symbol="RELIANCE", side="BUY", order_type="MARKET", quantity=10)


def _timeout() -> httpx.TimeoutException:
    return httpx.TimeoutException("timed out", request=httpx.Request("POST", "https://x"))


def _server_error() -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://x")
    return httpx.HTTPStatusError(
        "server error", request=request, response=httpx.Response(500, request=request)
    )


@pytest.fixture
def account_and_strategy():
    user_id = uuid.uuid4()
    account_id = uuid.uuid4()
    strategy_id = uuid.uuid4()

    with get_session() as session:
        session.add(
            User(
                id=user_id,
                email=f"test-{user_id}@example.invalid",
                hashed_password="x",
                role="Trader",
            )
        )
        session.commit()
    with get_session() as session:
        session.add(
            Account(
                id=account_id,
                user_id=user_id,
                broker="Upstox",
                account_type="Paper",
                capital_allocated=Decimal("100000.00"),
            )
        )
        session.commit()
    with get_session() as session:
        session.add(
            Strategy(
                id=strategy_id,
                account_id=account_id,
                name="execution-agent-test-strategy",
                asset_class="Equity",
                style="Intraday",
                status="Draft",
                max_drawdown_limit=Decimal("5.00"),
            )
        )
        session.commit()

    yield account_id, strategy_id

    with get_session() as session:
        session.query(OrderModel).filter(OrderModel.strategy_id == strategy_id).delete()
        session.query(Strategy).filter(Strategy.id == strategy_id).delete()
        session.query(Account).filter(Account.id == account_id).delete()
        session.query(User).filter(User.id == user_id).delete()
        session.commit()


@pytest.mark.asyncio
async def test_execute_signal_persists_the_order_row(account_and_strategy):
    account_id, strategy_id = account_and_strategy
    broker = ScriptedBrokerAdapter([_response(status="OPEN")], order_book_sequence=[[]])
    agent = ExecutionAgent(broker, get_session, poll_interval_seconds=0.01, max_polls=1)

    result = await agent.execute_signal(_order(), account_id=account_id, strategy_id=strategy_id)
    if result.tracking_task:
        await result.tracking_task

    assert result.order_response.broker_order_id == "ORD1"
    with get_session() as session:
        row = session.scalar(select(OrderModel).where(OrderModel.broker_order_id == "ORD1"))
        assert row is not None
        assert row.symbol == "RELIANCE"
        assert row.status == "OPEN"
        assert row.account_id == account_id
        assert row.strategy_id == strategy_id


@pytest.mark.asyncio
async def test_a_timeout_retries_with_backoff_then_succeeds(account_and_strategy):
    account_id, strategy_id = account_and_strategy
    broker = ScriptedBrokerAdapter(
        [_timeout(), _timeout(), _response(status="FILLED", filled_quantity=10)]
    )
    agent = ExecutionAgent(
        broker, get_session, max_retries=3, base_delay_seconds=0.001, poll_interval_seconds=0.01
    )

    result = await agent.execute_signal(_order(), account_id=account_id, strategy_id=strategy_id)

    assert result.retry_count == 2
    assert broker.place_calls == 3
    assert result.order_response.status == "FILLED"
    assert result.tracking_task is None  # already terminal -- nothing to track


@pytest.mark.asyncio
async def test_exhausting_all_retries_raises_execution_failed_and_persists_nothing(
    account_and_strategy,
):
    account_id, strategy_id = account_and_strategy
    broker = ScriptedBrokerAdapter([_timeout(), _timeout(), _timeout(), _timeout()])
    agent = ExecutionAgent(broker, get_session, max_retries=3, base_delay_seconds=0.001)

    with pytest.raises(ExecutionFailed):
        await agent.execute_signal(_order(), account_id=account_id, strategy_id=strategy_id)

    assert broker.place_calls == 4  # initial attempt + 3 retries
    with get_session() as session:
        rows = list(
            session.scalars(select(OrderModel).where(OrderModel.strategy_id == strategy_id))
        )
        assert rows == []


@pytest.mark.asyncio
async def test_a_non_timeout_error_propagates_immediately_without_retrying(account_and_strategy):
    account_id, strategy_id = account_and_strategy
    broker = ScriptedBrokerAdapter([_server_error()])
    agent = ExecutionAgent(broker, get_session, max_retries=3, base_delay_seconds=0.001)

    with pytest.raises(httpx.HTTPStatusError):
        await agent.execute_signal(_order(), account_id=account_id, strategy_id=strategy_id)

    assert broker.place_calls == 1  # no backoff retry for a 5xx -- that's the circuit breaker's job


@pytest.mark.asyncio
async def test_partial_fill_is_tracked_to_completion(account_and_strategy):
    account_id, strategy_id = account_and_strategy
    broker = ScriptedBrokerAdapter(
        [_response(status="PARTIALLY_FILLED", filled_quantity=4)],
        order_book_sequence=[
            [_response(status="PARTIALLY_FILLED", filled_quantity=7)],
            [_response(status="FILLED", filled_quantity=10)],
        ],
    )
    agent = ExecutionAgent(broker, get_session, poll_interval_seconds=0.01, max_polls=10)

    result = await agent.execute_signal(_order(), account_id=account_id, strategy_id=strategy_id)
    assert result.tracking_task is not None
    await asyncio.wait_for(result.tracking_task, timeout=2.0)

    with get_session() as session:
        row = session.scalar(select(OrderModel).where(OrderModel.broker_order_id == "ORD1"))
        assert row.status == "FILLED"


@pytest.mark.asyncio
async def test_tracking_gives_up_after_max_polls_without_reaching_a_terminal_state(
    account_and_strategy,
):
    account_id, strategy_id = account_and_strategy
    broker = ScriptedBrokerAdapter(
        [_response(status="OPEN")],
        order_book_sequence=[[_response(status="OPEN")]],
    )
    agent = ExecutionAgent(broker, get_session, poll_interval_seconds=0.01, max_polls=3)

    result = await agent.execute_signal(_order(), account_id=account_id, strategy_id=strategy_id)
    await asyncio.wait_for(result.tracking_task, timeout=2.0)

    assert broker.order_book_calls == 3
    with get_session() as session:
        row = session.scalar(select(OrderModel).where(OrderModel.broker_order_id == "ORD1"))
        assert row.status == "OPEN"  # never reached a terminal state -- stays as-is
