"""Integration test against the real Postgres service (docker-compose `postgres`)."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from src.agents.tools.skills import PortfolioStatusSkill
from src.core.db import get_session
from src.models.account import Account
from src.models.strategy import Strategy
from src.models.trading import PortfolioPosition
from src.models.user import User


def test_fetch_portfolio_status_reads_real_rows():
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
                name="test-seed-strategy",
                asset_class="Equity",
                style="Intraday",
                status="Draft",
                max_drawdown_limit=Decimal("5.00"),
            )
        )
        session.commit()

    with get_session() as session:
        session.add(
            PortfolioPosition(
                account_id=account_id,
                strategy_id=strategy_id,
                symbol="RELIANCE",
                net_quantity=10,
                avg_price=Decimal("2500.00"),
                unrealized_pnl=Decimal("150.00"),
                realized_pnl=Decimal("0.00"),
                as_of=datetime.now(UTC),
            )
        )
        session.commit()

    try:
        results = PortfolioStatusSkill().execute(account_id=str(account_id))
        assert len(results) == 1
        assert results[0]["symbol"] == "RELIANCE"
        assert results[0]["net_quantity"] == 10
        assert results[0]["unrealized_pnl"] == 150.0
    finally:
        with get_session() as session:
            session.query(PortfolioPosition).filter(
                PortfolioPosition.account_id == account_id
            ).delete()
            session.query(Strategy).filter(Strategy.id == strategy_id).delete()
            session.query(Account).filter(Account.id == account_id).delete()
            session.query(User).filter(User.id == user_id).delete()
            session.commit()
