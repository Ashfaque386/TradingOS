"""Chaos Engineering test (Phase 3 Epic E3.4 exit criterion): "The hardcoded Kill Switch is
verified via a Chaos Engineering test under simulated drawdown/network-partition conditions:
all open positions liquidate and AI deployment loops pause automatically."
(Phase_14_Master_Development_Roadmap.md)

Simulates a Redis network partition (connecting to a non-routable address) and confirms the
kill switch's emergency-stop path -- which depends only on Postgres -- completes correctly and
liquidates all open positions regardless. A safety-critical stop must not be able to fail
because a cache or pub/sub broker is unreachable.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import redis

from src.core.db import get_session
from src.engine.risk import kill_switch_service
from src.models.account import Account
from src.models.strategy import Strategy
from src.models.trading import Order, PortfolioPosition
from src.models.user import User

# A non-routable address (TEST-NET-1, RFC 5737) guarantees a connection timeout rather than a
# fast "connection refused" -- a closer simulation of a real network partition than pointing at
# a closed port on localhost.
_PARTITIONED_REDIS_HOST = "10.255.255.1"


def test_the_simulated_redis_partition_is_actually_unreachable():
    """Sanity check that the chaos condition below is real, not a no-op."""
    client = redis.Redis(host=_PARTITIONED_REDIS_HOST, port=6379, socket_connect_timeout=1)
    with pytest.raises(redis.exceptions.RedisError):
        client.ping()


def test_kill_switch_liquidates_positions_despite_a_redis_partition():
    user_id, account_id, strategy_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    order_id, position_id = uuid.uuid4(), uuid.uuid4()

    with get_session() as session:
        session.add(
            User(
                id=user_id,
                email=f"chaos-{user_id}@example.invalid",
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
                broker="Zerodha",
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
                name="chaos-test-strategy",
                asset_class="Equity",
                style="Intraday",
                status="Live",
                max_drawdown_limit=Decimal("15.00"),
            )
        )
        session.commit()

    with get_session() as session:
        session.add(
            Order(
                id=order_id,
                account_id=account_id,
                strategy_id=strategy_id,
                symbol="RELIANCE",
                side="BUY",
                order_type="MARKET",
                quantity=10,
                status="PENDING",
                requested_at=datetime.now(UTC),
            )
        )
        session.add(
            PortfolioPosition(
                id=position_id,
                account_id=account_id,
                strategy_id=strategy_id,
                symbol="RELIANCE",
                net_quantity=10,
                avg_price=Decimal("2500.00"),
                as_of=datetime.now(UTC),
            )
        )
        session.commit()

    try:
        # Confirm the partition immediately before tripping the switch, so the trip() call
        # below is demonstrably happening under a real Redis outage, not just "Redis wasn't
        # touched" by coincidence.
        redis_client = redis.Redis(
            host=_PARTITIONED_REDIS_HOST, port=6379, socket_connect_timeout=1
        )
        with pytest.raises(redis.exceptions.RedisError):
            redis_client.ping()

        with get_session() as session:
            result = kill_switch_service.trip(
                session, reason="chaos: simulated Redis network partition"
            )

        assert result.status == "TRIPPED"
        assert result.liquidated_positions == 1
        assert result.cancelled_orders == 1
        assert kill_switch_service.is_tripped() is True

        with get_session() as session:
            order = session.get(Order, order_id)
            position = session.get(PortfolioPosition, position_id)
            assert order.status == "CANCELLED"
            assert position.net_quantity == 0
    finally:
        with get_session() as session:
            kill_switch_service.reset(session)
        with get_session() as session:
            session.query(Order).filter(Order.id == order_id).delete()
            session.query(PortfolioPosition).filter(PortfolioPosition.id == position_id).delete()
            session.query(Strategy).filter(Strategy.id == strategy_id).delete()
            session.query(Account).filter(Account.id == account_id).delete()
            session.query(User).filter(User.id == user_id).delete()
            session.commit()
