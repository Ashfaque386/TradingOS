"""Monte Carlo persistence integration test (Phase 3 Epic E3.3/E3.4 exit criterion): the
95th-percentile Max Drawdown is actually computed AND stored in the real Postgres
`backtest_results` row, not just returned in-memory.
"""

import uuid
from datetime import date
from decimal import Decimal

from src.core.db import get_session
from src.engine.optimization.monte_carlo import run_monte_carlo_simulation
from src.engine.optimization.monte_carlo_persistence import (
    persist_monte_carlo_p95_max_drawdown,
)
from src.models.account import Account
from src.models.strategy import BacktestResult, Strategy, StrategyVersion
from src.models.user import User


def test_monte_carlo_p95_max_drawdown_is_persisted_to_the_real_backtest_result_row():
    user_id, account_id, strategy_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    version_id, backtest_result_id = uuid.uuid4(), uuid.uuid4()

    with get_session() as session:
        session.add(
            User(
                id=user_id,
                email=f"mc-persist-{user_id}@example.invalid",
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
                name="mc-persistence-test-strategy",
                asset_class="Equity",
                style="Intraday",
                status="Draft",
                max_drawdown_limit=Decimal("15.00"),
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
                validation_status="Passed",
            )
        )
        session.commit()

    with get_session() as session:
        session.add(
            BacktestResult(
                id=backtest_result_id,
                strategy_version_id=version_id,
                date_from=date(2023, 1, 1),
                date_to=date(2024, 1, 1),
                initial_capital=Decimal("100000.00"),
                sharpe_ratio=Decimal("1.20"),
                max_drawdown=Decimal("0.100"),
            )
        )
        session.commit()

    try:
        trade_returns = [0.05] * 9 + [-0.5]
        mc_result = run_monte_carlo_simulation(trade_returns, n_simulations=1_000, seed=42)

        with get_session() as session:
            updated = persist_monte_carlo_p95_max_drawdown(
                session, backtest_result_id, mc_result.percentile_95_max_drawdown
            )
            assert updated.monte_carlo_p95_max_drawdown == float(
                updated.monte_carlo_p95_max_drawdown
            )

        with get_session() as session:
            row = session.get(BacktestResult, backtest_result_id)
            assert row.monte_carlo_p95_max_drawdown is not None
            assert float(row.monte_carlo_p95_max_drawdown) > 0.0
            # Historical max_drawdown is untouched -- Monte Carlo augments, doesn't replace it.
            assert float(row.max_drawdown) == 0.100
    finally:
        with get_session() as session:
            session.query(BacktestResult).filter(BacktestResult.id == backtest_result_id).delete()
            session.query(StrategyVersion).filter(StrategyVersion.id == version_id).delete()
            session.query(Strategy).filter(Strategy.id == strategy_id).delete()
            session.query(Account).filter(Account.id == account_id).delete()
            session.query(User).filter(User.id == user_id).delete()
            session.commit()
