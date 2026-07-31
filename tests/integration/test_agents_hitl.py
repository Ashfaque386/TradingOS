"""REL-010 E10.8d: Orchestrator HITL (POST /agents/runs/{id}/retry|approve|reject) against the
real FastAPI app + real Postgres.

`retry` is real dispatched via the same detached `threading.Thread` machinery as
`/research/trigger` (src/api/routers/agents.py) -- every real LLM call that machinery would make
is exactly the kind of thing this codebase's existing test suite deliberately never exercises
over HTTP (confirmed: no test anywhere calls POST /research/trigger; see
tests/integration/test_agents_router_api.py's own docstring). `threading.Thread` itself is
patched here so the retry endpoint's real DB writes (new AgentRun row, `retried_from_run_id`)
are exercised without spawning an actual real graph run -- the same category of mock as
test_portfolio_manager_agent.py patching `complete` instead of calling a live LLM.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api.main import app
from src.core.db import get_session
from src.core.security import ROLE_READ_ONLY_AUDITOR, ROLE_RISK_MANAGER
from src.models.account import Account
from src.models.agent import AgentRun
from src.models.strategy import BacktestResult, Strategy, StrategyVersion
from src.models.user import User
from tests.auth_helpers import auth_header, cleanup_user, create_authenticated_user

client = TestClient(app)


def _seed_run(status: str) -> uuid.UUID:
    with get_session() as session:
        run = AgentRun(
            graph_thread_id=str(uuid.uuid4()),
            agent_name="TradingOSGraph",
            status=status,
            started_at=datetime.now(UTC),
        )
        session.add(run)
        session.commit()
        return run.id


def _cleanup_run(run_id: uuid.UUID) -> None:
    with get_session() as session:
        session.query(AgentRun).filter(
            (AgentRun.id == run_id) | (AgentRun.retried_from_run_id == run_id)
        ).delete(synchronize_session=False)
        session.commit()


def test_retry_requires_the_gated_role():
    run_id = _seed_run("Failed")
    user_id, token = create_authenticated_user(ROLE_READ_ONLY_AUDITOR)
    try:
        response = client.post(f"/api/v1/agents/runs/{run_id}/retry", headers=auth_header(token))
        assert response.status_code == 403
    finally:
        cleanup_user(user_id)
        _cleanup_run(run_id)


def test_retry_404s_for_an_unknown_run():
    user_id, token = create_authenticated_user(ROLE_RISK_MANAGER)
    try:
        response = client.post(
            f"/api/v1/agents/runs/{uuid.uuid4()}/retry", headers=auth_header(token)
        )
        assert response.status_code == 404
    finally:
        cleanup_user(user_id)


def test_retry_400s_for_a_run_that_is_not_failed():
    run_id = _seed_run("Completed")
    user_id, token = create_authenticated_user(ROLE_RISK_MANAGER)
    try:
        response = client.post(f"/api/v1/agents/runs/{run_id}/retry", headers=auth_header(token))
        assert response.status_code == 400
    finally:
        cleanup_user(user_id)
        _cleanup_run(run_id)


@patch("src.api.routers.agents.threading.Thread")
def test_retry_creates_a_real_new_run_linked_to_the_failed_one(mock_thread):
    run_id = _seed_run("Failed")
    user_id, token = create_authenticated_user(ROLE_RISK_MANAGER)
    new_run_id = None
    try:
        response = client.post(f"/api/v1/agents/runs/{run_id}/retry", headers=auth_header(token))
        assert response.status_code == 202
        body = response.json()
        assert body["retried_from_run_id"] == str(run_id)
        assert body["status"] == "Running"
        new_run_id = uuid.UUID(body["run_id"])

        mock_thread.assert_called_once()
        mock_thread.return_value.start.assert_called_once()

        with get_session() as session:
            new_run = session.get(AgentRun, new_run_id)
            assert new_run is not None
            assert new_run.retried_from_run_id == run_id
            assert new_run.status == "Running"
    finally:
        cleanup_user(user_id)
        if new_run_id is not None:
            _cleanup_run(new_run_id)
        _cleanup_run(run_id)


def test_approve_records_a_real_audited_human_decision():
    run_id = _seed_run("Completed")
    user_id, token = create_authenticated_user(ROLE_RISK_MANAGER)
    try:
        response = client.post(f"/api/v1/agents/runs/{run_id}/approve", headers=auth_header(token))
        assert response.status_code == 200
        assert response.json()["human_decision"] == "Approved"

        with get_session() as session:
            run = session.get(AgentRun, run_id)
            assert run is not None
            assert run.human_decision == "Approved"
    finally:
        cleanup_user(user_id)
        _cleanup_run(run_id)


def _seed_strategy_reaching_papertrading_via_run(run_id: uuid.UUID) -> uuid.UUID:
    """Real lineage: a "backtesting"-node child AgentRun (parent_run_id=run_id) whose
    BacktestResult.agent_run_id points at it, whose strategy_version_id resolves to a Strategy
    already sitting at "PaperTrading" -- exactly the shape `_strategy_from_run_lineage` walks."""
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
                email=f"hitl-test-{user_id}@example.invalid",
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
                name="hitl-test-strategy",
                asset_class="Equity",
                style="Intraday",
                status="PaperTrading",
                max_drawdown_limit=Decimal("15.00"),
                current_version_id=version_id,
            )
        )
        session.add(
            StrategyVersion(
                id=version_id,
                strategy_id=strategy_id,
                version_no=1,
                python_code="def generate_signals(data):\n    return data",
                validation_status="Passed",
            )
        )
        session.commit()

        backtesting_child = AgentRun(
            graph_thread_id=str(uuid.uuid4()),
            agent_name="backtesting",
            parent_run_id=run_id,
            status="Completed",
            started_at=datetime.now(UTC),
        )
        session.add(backtesting_child)
        session.flush()
        session.add(
            BacktestResult(
                strategy_version_id=version_id,
                agent_run_id=backtesting_child.id,
                date_from=datetime.now(UTC).date(),
                date_to=datetime.now(UTC).date(),
                initial_capital=Decimal("100000.00"),
                total_trades=10,
            )
        )
        session.commit()
    return strategy_id


def _cleanup_strategy_lineage(strategy_id: uuid.UUID) -> None:
    with get_session() as session:
        strategy = session.get(Strategy, strategy_id)
        if strategy is None:
            return
        account_id = strategy.account_id
        version_id = strategy.current_version_id
        session.query(BacktestResult).filter(
            BacktestResult.strategy_version_id == version_id
        ).delete()
        strategy.current_version_id = None
        session.commit()
    with get_session() as session:
        session.query(StrategyVersion).filter(StrategyVersion.id == version_id).delete()
        session.query(Strategy).filter(Strategy.id == strategy_id).delete()
        session.commit()
    with get_session() as session:
        account = session.get(Account, account_id)
        user_id = account.user_id if account is not None else None
        session.query(Account).filter(Account.id == account_id).delete()
        session.commit()
    if user_id is not None:
        with get_session() as session:
            session.query(User).filter(User.id == user_id).delete()
            session.commit()


def test_reject_requires_a_reason_and_overrides_papertrading_strategy_to_deprecated():
    run_id = _seed_run("Completed")
    strategy_id = _seed_strategy_reaching_papertrading_via_run(run_id)
    user_id, token = create_authenticated_user(ROLE_RISK_MANAGER)
    try:
        response = client.post(
            f"/api/v1/agents/runs/{run_id}/reject",
            json={"reason": "Backtest Sharpe looks overfit on manual review."},
            headers=auth_header(token),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["human_decision"] == "Rejected"
        assert body["strategy_id"] == str(strategy_id)
        assert body["strategy_status"] == "Deprecated"

        with get_session() as session:
            strategy = session.get(Strategy, strategy_id)
            assert strategy is not None
            assert strategy.status == "Deprecated"
    finally:
        cleanup_user(user_id)
        _cleanup_strategy_lineage(strategy_id)
        with get_session() as session:
            session.query(AgentRun).filter(AgentRun.parent_run_id == run_id).delete()
            session.commit()
        _cleanup_run(run_id)
