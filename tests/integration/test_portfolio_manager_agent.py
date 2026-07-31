"""REL-010 E10.5: Portfolio Manager Agent against the real FastAPI app + real Postgres --
mocks only the LLM call and the broker margin fetch (a fake, not a live account)."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.nodes.portfolio_manager_agent import generate_allocation_recommendation
from src.brokers.base import Margin
from src.core.db import get_session
from src.models.account import Account
from src.models.portfolio_allocation_recommendation import PortfolioAllocationRecommendation
from src.models.strategy import BacktestResult, Strategy, StrategyVersion
from src.models.user import User

_STRATEGY_CODE = "def generate_signals(data):\n    return data"


def _seed_live_strategy_with_backtest(sharpe_ratio: float = 1.8) -> tuple:
    user_id, account_id, strategy_id, version_id = (
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
    )
    with get_session() as session:
        session.add(
            User(
                id=user_id,
                email=f"portfolio-manager-test-{user_id}@example.invalid",
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
        strategy = Strategy(
            id=strategy_id,
            account_id=account_id,
            name="portfolio-manager-test-strategy",
            asset_class="Equity",
            style="Intraday",
            status="Live",
            max_drawdown_limit=Decimal("15.00"),
        )
        session.add(strategy)
        session.flush()
        session.add(
            StrategyVersion(
                id=version_id,
                strategy_id=strategy_id,
                version_no=1,
                python_code=_STRATEGY_CODE,
                validation_status="Passed",
            )
        )
        strategy.current_version_id = version_id
        session.commit()

        session.add(
            BacktestResult(
                strategy_version_id=version_id,
                date_from=datetime.now(UTC).date() - timedelta(days=365),
                date_to=datetime.now(UTC).date(),
                initial_capital=Decimal("100000.00"),
                sharpe_ratio=Decimal(str(sharpe_ratio)),
                total_trades=100,
            )
        )
        session.commit()

    return user_id, account_id, strategy_id, version_id


def _cleanup(user_id, account_id, strategy_id, version_id) -> None:
    with get_session() as session:
        session.query(PortfolioAllocationRecommendation).delete()
        session.query(BacktestResult).filter(
            BacktestResult.strategy_version_id == version_id
        ).delete()
        session.query(StrategyVersion).filter(StrategyVersion.id == version_id).delete()
        session.query(Strategy).filter(Strategy.id == strategy_id).delete()
        session.query(Account).filter(Account.id == account_id).delete()
        session.query(User).filter(User.id == user_id).delete()
        session.commit()


def _fake_llm_response(content: str):
    class _Choice:
        def __init__(self, content: str) -> None:
            self.message = type("Message", (), {"content": content})()

    class _Response:
        def __init__(self, content: str) -> None:
            self.choices = [_Choice(content)]

    return _Response(content)


@pytest.mark.asyncio
@patch("src.agents.nodes.portfolio_manager_agent.complete")
async def test_generates_and_persists_a_real_recommendation_referencing_real_input_data(
    mock_complete,
):
    ids = _seed_live_strategy_with_backtest(sharpe_ratio=1.8)
    _, _, strategy_id, _ = ids
    mock_complete.return_value = _fake_llm_response(
        f'{{"weights": [{{"strategy_id": "{strategy_id}", '
        f'"strategy_name": "portfolio-manager-test-strategy", "weight_pct": 60.0}}], '
        f'"rationale": "Strong real Sharpe of 1.8 supports a 60% weight."}}'
    )
    fake_broker = AsyncMock()
    fake_broker.get_margin.return_value = Margin(available_margin=50000.0, used_margin=10000.0)

    try:
        with get_session() as session:
            recommendation = await generate_allocation_recommendation(session, fake_broker)

        assert recommendation is not None
        assert recommendation.status == "Proposed"
        assert "1.8" in recommendation.rationale
        assert recommendation.recommendations["weights"][0]["weight_pct"] == 60.0

        with get_session() as session:
            row = session.get(PortfolioAllocationRecommendation, recommendation.id)
            assert row is not None
            assert row.status == "Proposed"
    finally:
        _cleanup(*ids)
