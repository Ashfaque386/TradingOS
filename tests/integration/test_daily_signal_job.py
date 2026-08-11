"""src/engine/paper_trading/daily_signal_job.py integration tests (REL-034), against the real
Postgres + real data lake + real (warm-pool) sandbox execution.

Covers the deterministic guard clauses without needing a live market session (see the smoke
test performed manually during implementation for the full live-fill path -- confirmed working
end-to-end: real sandbox execution -> real entries_exits -> real BUY transition -> real
position sizing -> a real broker quote call, which correctly returned "no usable depth" outside
real NSE trading hours, an honest outcome, not a code defect).
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from src.agents.control import set_agent_enabled
from src.core.db import get_session
from src.core.security import ROLE_SYSTEM_ADMINISTRATOR
from src.engine.paper_trading.daily_signal_job import (
    PAPER_TRADING_AGENT_NAME,
    _process_fno_strategy,
    _process_strategy,
    run_daily_paper_trading_cycle,
)
from src.engine.paper_trading.execution_service import NoLiquidityError
from src.engine.paper_trading.paper_account import get_paper_account
from src.engine.sandbox.backtest_runner import EntryExitPoint, RealBacktestOutcome
from src.models.agent import AgentControlState
from src.models.paper_trading import PaperTrade
from src.models.strategy import Strategy, StrategyVersion
from src.models.user import User

_LEG_CE = {
    "symbol": "INFY26AUG2000CE",
    "option_type": "CE",
    "strike": 2000.0,
    "side": "buy",
    "quantity": 50,
}
_LEG_PE = {
    "symbol": "INFY26AUG2000PE",
    "option_type": "PE",
    "strike": 2000.0,
    "side": "sell",
    "quantity": 50,
}


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
        session.query(PaperTrade).filter(PaperTrade.strategy_id == strategy_id).delete()
        session.query(StrategyVersion).filter(StrategyVersion.strategy_id == strategy_id).delete()
        session.query(Strategy).filter(Strategy.id == strategy_id).delete()
        session.commit()


def _seed_fno_strategy(
    *, option_legs: list[dict[str, Any]] | None, option_expiry: date | None
) -> tuple[uuid.UUID, uuid.UUID]:
    """REL-035: an F&O strategy with a real, current `StrategyVersion` row carrying the
    persisted chain-grounded legs/expiry -- `_seed_strategy` alone (no version) only exercises
    the equity-path guard clauses, not the F&O leg-persistence path this seeds for."""
    strategy_id, account_id = _seed_strategy(asset_class="F&O", universe=["INFY"])
    with get_session() as session:
        version = StrategyVersion(
            strategy_id=strategy_id,
            version_no=1,
            python_code="# placeholder -- run_real_backtest is mocked in these tests",
            validation_status="Pass",
            option_legs=option_legs,
            option_expiry=option_expiry,
        )
        session.add(version)
        session.flush()
        strategy = session.get(Strategy, strategy_id)
        strategy.current_version_id = version.id
        session.commit()
    return strategy_id, account_id


def _seed_paper_trade(
    *,
    symbol: str,
    side: str,
    quantity: int,
    account_id: uuid.UUID,
    strategy_id: uuid.UUID,
    instrument_type: str = "EQUITY",
) -> uuid.UUID:
    with get_session() as session:
        trade = PaperTrade(
            account_id=account_id,
            strategy_id=strategy_id,
            instrument_type=instrument_type,
            symbol=symbol,
            side=side,
            requested_quantity=quantity,
            filled_quantity=quantity,
            reference_price=100.0,
            fill_price=100.0,
            slippage_bps=0.0,
            depth_snapshot={"buy": [], "sell": [], "fully_filled": True},
            executed_at=datetime.now(UTC),
        )
        session.add(trade)
        session.commit()
        return trade.id


@pytest.mark.asyncio
async def test_fo_strategy_with_no_persisted_legs_is_skipped_not_guessed_at():
    strategy_id, account_id = _seed_fno_strategy(option_legs=None, option_expiry=None)
    try:
        with get_session() as session:
            strategy = session.get(Strategy, strategy_id)
            result = await _process_fno_strategy(
                strategy, account_id=str(account_id), not_after=date.today()
            )
        assert result.action == "SKIPPED"
        assert result.reason == "no grounded option legs persisted for the current version"
    finally:
        _cleanup_strategy(strategy_id)


@pytest.mark.asyncio
async def test_fo_strategy_with_expired_plan_is_skipped():
    strategy_id, account_id = _seed_fno_strategy(
        option_legs=[_LEG_CE, _LEG_PE], option_expiry=date.today() - timedelta(days=1)
    )
    try:
        with get_session() as session:
            strategy = session.get(Strategy, strategy_id)
            result = await _process_fno_strategy(
                strategy, account_id=str(account_id), not_after=date.today()
            )
        assert result.action == "SKIPPED"
        assert result.reason is not None and "expired" in result.reason
    finally:
        _cleanup_strategy(strategy_id)


@pytest.mark.asyncio
@patch("src.engine.paper_trading.daily_signal_job.execute_paper_trade", new_callable=AsyncMock)
@patch("src.engine.paper_trading.daily_signal_job.build_broker")
@patch("src.engine.paper_trading.daily_signal_job.run_real_backtest")
async def test_fo_full_entry_opens_every_leg(mock_backtest, mock_build_broker, mock_execute):
    strategy_id, account_id = _seed_fno_strategy(
        option_legs=[_LEG_CE, _LEG_PE], option_expiry=date.today() + timedelta(days=14)
    )
    mock_backtest.return_value = RealBacktestOutcome(
        passed=True,
        error=None,
        symbol_used="INFY",
        entries_exits=[EntryExitPoint(date="2024-07-19", entry=True, exit=False)],
    )
    mock_build_broker.return_value = object()
    mock_execute.side_effect = [
        SimpleNamespace(id=uuid.uuid4()),
        SimpleNamespace(id=uuid.uuid4()),
    ]
    try:
        with get_session() as session:
            strategy = session.get(Strategy, strategy_id)
            result = await _process_fno_strategy(
                strategy, account_id=str(account_id), not_after=date.today()
            )

        assert result.action == "BUY"
        assert result.trade_id is not None and len(result.trade_id.split(",")) == 2
        assert mock_execute.await_count == 2
        calls_by_symbol = {c.kwargs["symbol"]: c.kwargs for c in mock_execute.await_args_list}
        assert calls_by_symbol["INFY26AUG2000CE"]["side"] == "BUY"  # leg's own side: buy
        assert calls_by_symbol["INFY26AUG2000CE"]["quantity"] == 50
        assert calls_by_symbol["INFY26AUG2000CE"]["instrument_type"] == "CE"
        assert calls_by_symbol["INFY26AUG2000CE"]["underlying"] == "INFY"
        assert calls_by_symbol["INFY26AUG2000PE"]["side"] == "SELL"  # leg's own side: sell
        assert calls_by_symbol["INFY26AUG2000PE"]["quantity"] == 50
    finally:
        _cleanup_strategy(strategy_id)


@pytest.mark.asyncio
@patch("src.engine.paper_trading.daily_signal_job.execute_paper_trade", new_callable=AsyncMock)
@patch("src.engine.paper_trading.daily_signal_job.build_broker")
@patch("src.engine.paper_trading.daily_signal_job.run_real_backtest")
async def test_fo_full_exit_closes_every_open_leg(mock_backtest, mock_build_broker, mock_execute):
    strategy_id, account_id = _seed_fno_strategy(
        option_legs=[_LEG_CE, _LEG_PE], option_expiry=date.today() + timedelta(days=14)
    )
    _seed_paper_trade(
        symbol="INFY26AUG2000CE",
        side="BUY",  # opened long, per _LEG_CE's "buy"
        quantity=50,
        account_id=account_id,
        strategy_id=strategy_id,
        instrument_type="CE",
    )
    _seed_paper_trade(
        symbol="INFY26AUG2000PE",
        side="SELL",  # opened short, per _LEG_PE's "sell"
        quantity=50,
        account_id=account_id,
        strategy_id=strategy_id,
        instrument_type="PE",
    )
    mock_backtest.return_value = RealBacktestOutcome(
        passed=True,
        error=None,
        symbol_used="INFY",
        entries_exits=[EntryExitPoint(date="2024-07-19", entry=False, exit=True)],
    )
    mock_build_broker.return_value = object()
    mock_execute.side_effect = [
        SimpleNamespace(id=uuid.uuid4()),
        SimpleNamespace(id=uuid.uuid4()),
    ]
    try:
        with get_session() as session:
            strategy = session.get(Strategy, strategy_id)
            result = await _process_fno_strategy(
                strategy, account_id=str(account_id), not_after=date.today()
            )

        assert result.action == "SELL"
        assert mock_execute.await_count == 2
        calls_by_symbol = {c.kwargs["symbol"]: c.kwargs for c in mock_execute.await_args_list}
        # Closing side is the OPPOSITE of how each leg was opened.
        assert calls_by_symbol["INFY26AUG2000CE"]["side"] == "SELL"
        assert calls_by_symbol["INFY26AUG2000PE"]["side"] == "BUY"
    finally:
        _cleanup_strategy(strategy_id)


@pytest.mark.asyncio
@patch("src.engine.paper_trading.daily_signal_job.execute_paper_trade", new_callable=AsyncMock)
@patch("src.engine.paper_trading.daily_signal_job.build_broker")
@patch("src.engine.paper_trading.daily_signal_job.run_real_backtest")
async def test_fo_partial_fill_reports_exactly_which_legs_filled(
    mock_backtest, mock_build_broker, mock_execute
):
    strategy_id, account_id = _seed_fno_strategy(
        option_legs=[_LEG_CE, _LEG_PE], option_expiry=date.today() + timedelta(days=14)
    )
    mock_backtest.return_value = RealBacktestOutcome(
        passed=True,
        error=None,
        symbol_used="INFY",
        entries_exits=[EntryExitPoint(date="2024-07-19", entry=True, exit=False)],
    )
    mock_build_broker.return_value = object()
    filled_id = uuid.uuid4()
    mock_execute.side_effect = [
        SimpleNamespace(id=filled_id),
        NoLiquidityError("no usable depth"),
    ]
    try:
        with get_session() as session:
            strategy = session.get(Strategy, strategy_id)
            result = await _process_fno_strategy(
                strategy, account_id=str(account_id), not_after=date.today()
            )

        assert result.action == "PARTIAL_FILL"
        assert result.trade_id == str(filled_id)
        assert result.reason is not None
        assert "INFY26AUG2000CE" in result.reason
        assert "INFY26AUG2000PE" in result.reason
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
