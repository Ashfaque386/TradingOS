"""LiveExecutionPipeline order persistence (spec T101/BUG-F): a placed order reconciles to a
real `Order` row + audit entry via `ExecutionAgent`, the exact same write path the manual
`POST /orders` Live branch uses -- once `account_id`/`strategy_id` are configured. Without them
(this class's pre-T101 default), `handle_tick` stays pure signal-routing with no DB write, per
`tests/unit/test_execution_pipeline.py`'s own existing coverage.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from src.core.db import get_session
from src.engine.live.execution_pipeline import (
    LiveExecutionPipeline,
    SymbolState,
    Tick,
    TradeSignal,
)
from src.engine.risk.kill_switch import MaxDrawdownKillSwitch
from src.models.account import Account
from src.models.strategy import Strategy
from src.models.trading import Order as OrderModel
from src.models.user import User
from tests.unit.test_execution_pipeline import FakeBrokerAdapter


@pytest.fixture
def account_and_strategy():
    user_id = uuid.uuid4()
    account_id = uuid.uuid4()
    strategy_id = uuid.uuid4()
    with get_session() as session:
        session.add(
            User(
                id=user_id,
                email=f"test-pipeline-persist-{user_id}@example.invalid",
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
                name="execution-pipeline-persist-test-strategy",
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


def _always_buy(state: SymbolState) -> TradeSignal:
    return TradeSignal(symbol=state.symbol, side="BUY", quantity=1)


@pytest.mark.asyncio
async def test_handle_tick_persists_an_order_row_when_account_and_strategy_are_configured(
    account_and_strategy,
):
    account_id, strategy_id = account_and_strategy
    pipeline = LiveExecutionPipeline(
        broker=FakeBrokerAdapter(),
        signal_generator=_always_buy,
        kill_switch=MaxDrawdownKillSwitch(),
        account_id=account_id,
        strategy_id=strategy_id,
    )

    result = await pipeline.handle_tick(
        Tick(symbol="RELIANCE", price=2500.0, timestamp=datetime.now(UTC))
    )

    assert result is not None
    assert result.broker_order_id == "ORD1"
    with get_session() as session:
        row = session.scalar(select(OrderModel).where(OrderModel.broker_order_id == "ORD1"))
        assert row is not None
        assert row.account_id == account_id
        assert row.strategy_id == strategy_id
        assert row.symbol == "RELIANCE"


@pytest.mark.asyncio
async def test_handle_tick_stays_persistence_free_without_account_and_strategy():
    pipeline = LiveExecutionPipeline(
        broker=FakeBrokerAdapter(),
        signal_generator=_always_buy,
        kill_switch=MaxDrawdownKillSwitch(),
    )

    result = await pipeline.handle_tick(
        Tick(symbol="TCS", price=3500.0, timestamp=datetime.now(UTC))
    )

    assert result is not None
    with get_session() as session:
        row = session.scalar(select(OrderModel).where(OrderModel.symbol == "TCS"))
        assert row is None
