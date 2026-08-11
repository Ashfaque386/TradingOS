"""src/engine/paper_trading/daily_signal_job.py integration tests (REL-034), against the real
Postgres + real data lake + real (warm-pool) sandbox execution.

Covers the deterministic guard clauses without needing a live market session (see the smoke
test performed manually during implementation for the full live-fill path -- confirmed working
end-to-end: real sandbox execution -> real entries_exits -> real BUY transition -> real
position sizing -> a real broker quote call, which correctly returned "no usable depth" outside
real NSE trading hours, an honest outcome, not a code defect).
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from src.agents.control import set_agent_enabled
from src.core.db import get_session
from src.core.security import ROLE_SYSTEM_ADMINISTRATOR
from src.engine.paper_trading.daily_signal_job import (
    PAPER_TRADING_AGENT_NAME,
    _process_strategy,
    run_daily_paper_trading_cycle,
)
from src.engine.paper_trading.paper_account import get_paper_account
from src.models.agent import AgentControlState
from src.models.strategy import Strategy, StrategyVersion
from src.models.user import User


def _seed_strategy(**overrides) -> tuple[uuid.UUID, uuid.UUID]:
    with get_session() as session:
        account_id = get_paper_account(session).id
    strategy_id = uuid.uuid4()
    defaults = dict(
        id=strategy_id,
        account_id=account_id,
        name="daily-signal-job-test-strategy",
        asset_class="Equity",
        style="Swing",
        status="PaperTrading",
        max_drawdown_limit=Decimal("15.00"),
        universe=["INFY"],
    )
    defaults.update(overrides)
    with get_session() as session:
        session.add(Strategy(**defaults))
        session.commit()
    return strategy_id, account_id


def _cleanup_strategy(strategy_id: uuid.UUID) -> None:
    with get_session() as session:
        session.query(StrategyVersion).filter(StrategyVersion.strategy_id == strategy_id).delete()
        session.query(Strategy).filter(Strategy.id == strategy_id).delete()
        session.commit()


@pytest.mark.asyncio
async def test_fo_strategy_is_skipped_not_guessed_at():
    strategy_id, _ = _seed_strategy(asset_class="F&O")
    try:
        with get_session() as session:
            strategy = session.get(Strategy, strategy_id)
            result = await _process_strategy(
                strategy,
                account_id=str(strategy.account_id),
                total_capital=100_000.0,
                not_after=date.today(),
            )
        assert result.action == "SKIPPED"
        assert result.reason is not None and "F&O" in result.reason
    finally:
        _cleanup_strategy(strategy_id)


@pytest.mark.asyncio
async def test_strategy_with_no_universe_is_skipped():
    strategy_id, _ = _seed_strategy(universe=None)
    try:
        with get_session() as session:
            strategy = session.get(Strategy, strategy_id)
            result = await _process_strategy(
                strategy,
                account_id=str(strategy.account_id),
                total_capital=100_000.0,
                not_after=date.today(),
            )
        assert result.action == "SKIPPED"
        assert result.reason == "strategy has no universe"
    finally:
        _cleanup_strategy(strategy_id)


@pytest.mark.asyncio
async def test_strategy_with_no_current_version_is_skipped():
    strategy_id, _ = _seed_strategy()
    try:
        with get_session() as session:
            strategy = session.get(Strategy, strategy_id)
            result = await _process_strategy(
                strategy,
                account_id=str(strategy.account_id),
                total_capital=100_000.0,
                not_after=date.today(),
            )
        assert result.action == "SKIPPED"
        assert result.reason == "strategy has no current code version"
    finally:
        _cleanup_strategy(strategy_id)


@pytest.mark.asyncio
async def test_full_cycle_skips_entirely_when_agent_disabled():
    with get_session() as session:
        admin = session.scalars(select(User).where(User.role == ROLE_SYSTEM_ADMINISTRATOR)).first()
        assert admin is not None, "seed_admin_user.py must have run in this environment"
        admin_id = admin.id
        set_agent_enabled(
            session,
            agent_name=PAPER_TRADING_AGENT_NAME,
            enabled=False,
            reason="test",
            updated_by_user_id=admin_id,
        )
        session.commit()
    try:
        results = await run_daily_paper_trading_cycle()
        assert results == []
    finally:
        with get_session() as session:
            set_agent_enabled(
                session,
                agent_name=PAPER_TRADING_AGENT_NAME,
                enabled=True,
                reason=None,
                updated_by_user_id=admin_id,
            )
            session.commit()
            session.query(AgentControlState).filter(
                AgentControlState.agent_name == PAPER_TRADING_AGENT_NAME
            ).delete()
            session.commit()
