"""Integration test: Strategy Factory persisting validation status to a real Postgres row."""

import uuid
from decimal import Decimal

from src.core.db import get_session
from src.engine.sandbox.strategy_factory import run_strategy_factory_pipeline
from src.models.account import Account
from src.models.strategy import Strategy, StrategyVersion
from src.models.user import User


def test_strategy_factory_updates_real_strategy_version_row():
    user_id = uuid.uuid4()
    account_id = uuid.uuid4()
    strategy_id = uuid.uuid4()
    version_id = uuid.uuid4()

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
                name="factory-test-strategy",
                asset_class="Equity",
                style="Intraday",
                status="Draft",
                max_drawdown_limit=Decimal("5.00"),
            )
        )
        session.commit()

    with get_session() as session:
        session.add(
            StrategyVersion(
                id=version_id,
                strategy_id=strategy_id,
                version_no=1,
                python_code="",
                validation_status="Pending",
            )
        )
        session.commit()

    try:
        code = "def run_backtest(data, config):\n    return {'sharpe_ratio': 1.1}\n"
        result = run_strategy_factory_pipeline(code, strategy_version_id=str(version_id))

        assert result.status == "Passed"
        with get_session() as session:
            row = session.get(StrategyVersion, version_id)
            assert row.validation_status == "Passed"
    finally:
        with get_session() as session:
            session.query(StrategyVersion).filter(StrategyVersion.id == version_id).delete()
            session.query(Strategy).filter(Strategy.id == strategy_id).delete()
            session.query(Account).filter(Account.id == account_id).delete()
            session.query(User).filter(User.id == user_id).delete()
            session.commit()


def test_strategy_factory_marks_failed_status_on_real_row():
    user_id = uuid.uuid4()
    account_id = uuid.uuid4()
    strategy_id = uuid.uuid4()
    version_id = uuid.uuid4()

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
                name="factory-fail-test-strategy",
                asset_class="Equity",
                style="Intraday",
                status="Draft",
                max_drawdown_limit=Decimal("5.00"),
            )
        )
        session.commit()

    with get_session() as session:
        session.add(
            StrategyVersion(
                id=version_id,
                strategy_id=strategy_id,
                version_no=1,
                python_code="",
                validation_status="Pending",
            )
        )
        session.commit()

    try:
        result = run_strategy_factory_pipeline(
            "import os\nos.system('ls')", strategy_version_id=str(version_id)
        )

        assert result.status == "Failed"
        with get_session() as session:
            row = session.get(StrategyVersion, version_id)
            assert row.validation_status == "Failed"
            assert "os" in row.validator_feedback
    finally:
        with get_session() as session:
            session.query(StrategyVersion).filter(StrategyVersion.id == version_id).delete()
            session.query(Strategy).filter(Strategy.id == strategy_id).delete()
            session.query(Account).filter(Account.id == account_id).delete()
            session.query(User).filter(User.id == user_id).delete()
            session.commit()
