"""spec 002 US1: `/api/v1/strategies/{id}/promote` must not be a back door around the real
Paper-Trading approval gate (`src/orchestration/approvals.py`).

Before this fix, `/promote {to_status: "PaperTrading"}` set `Strategy.status` directly with no
reference to `ApprovalRequest` state at all -- a strategy whose most recent approval was
*rejected* could still be promoted straight into Paper Trading by the same SA/PortfolioManager
roles that decide approvals. These tests must fail against the pre-fix code and pass after
`has_approved_paper_request()` (src/orchestration/approvals.py) gates the transition.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from src.api.main import app
from src.core.db import get_session
from src.core.security import ROLE_PORTFOLIO_MANAGER, ROLE_SYSTEM_ADMINISTRATOR
from src.models.account import Account
from src.models.approval import ApprovalRequest
from src.models.strategy import Strategy, StrategyVersion
from src.models.user import User
from tests.auth_helpers import auth_header, cleanup_user, create_authenticated_user

client = TestClient(app)

_CODE = "def generate_signals(data):\n    return data"


def _seed_strategy(status: str) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """User -> Account -> Strategy(status=<status>) + one code version. Returns
    (user_id, account_id, strategy_id)."""
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
                email=f"promote-bypass-{user_id}@example.invalid",
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
            name="promote-bypass-test-strategy",
            asset_class="Equity",
            style="Intraday",
            status=status,
            max_drawdown_limit=Decimal("15.00"),
        )
        session.add(strategy)
        session.flush()
        session.add(
            StrategyVersion(
                id=version_id,
                strategy_id=strategy_id,
                version_no=1,
                python_code=_CODE,
                validation_status="Passed",
            )
        )
        session.flush()
        strategy.current_version_id = version_id
        session.commit()
    return user_id, account_id, strategy_id


def _add_approval_request(strategy_id: uuid.UUID, status: str) -> uuid.UUID:
    with get_session() as session:
        approval = ApprovalRequest(
            run_id=None,
            strategy_id=strategy_id,
            strategy_version_id=None,
            recommendation_artefact_id=None,
            status=status,
            decided_by="pm@example.invalid" if status != "pending" else None,
            decided_at=datetime.now(UTC) if status != "pending" else None,
            reason="Backtest looked overfit." if status == "rejected" else None,
            created_at=datetime.now(UTC),
        )
        session.add(approval)
        session.commit()
        return approval.id


def _cleanup(user_id: uuid.UUID, account_id: uuid.UUID, strategy_id: uuid.UUID) -> None:
    with get_session() as session:
        session.query(ApprovalRequest).filter(ApprovalRequest.strategy_id == strategy_id).delete()
        strategy = session.get(Strategy, strategy_id)
        version_id = strategy.current_version_id if strategy is not None else None
        if strategy is not None:
            strategy.current_version_id = None
        session.commit()
    with get_session() as session:
        if version_id is not None:
            session.query(StrategyVersion).filter(StrategyVersion.id == version_id).delete()
        session.query(Strategy).filter(Strategy.id == strategy_id).delete()
        session.query(Account).filter(Account.id == account_id).delete()
        session.commit()
    cleanup_user(user_id)


def _strategy_status(strategy_id: uuid.UUID) -> str | None:
    with get_session() as session:
        s = session.get(Strategy, strategy_id)
        return s.status if s is not None else None


def test_promote_to_paper_trading_is_refused_with_no_approval_on_record():
    user_id, account_id, strategy_id = _seed_strategy("Backtesting")
    sa_user_id, sa_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        resp = client.post(
            f"/api/v1/strategies/{strategy_id}/promote",
            json={"to_status": "PaperTrading"},
            headers=auth_header(sa_token),
        )
        assert resp.status_code == 409, resp.text
        assert _strategy_status(strategy_id) == "Backtesting"
    finally:
        cleanup_user(sa_user_id)
        _cleanup(user_id, account_id, strategy_id)


def test_promote_to_paper_trading_is_refused_after_a_rejection():
    # This is the exact bypass this fix closes: a rejected strategy, promoted through the
    # generic Kanban endpoint instead of the dedicated approval flow.
    user_id, account_id, strategy_id = _seed_strategy("Deprecated")
    _add_approval_request(strategy_id, "rejected")
    pm_user_id, pm_token = create_authenticated_user(ROLE_PORTFOLIO_MANAGER)
    try:
        resp = client.post(
            f"/api/v1/strategies/{strategy_id}/promote",
            json={"to_status": "PaperTrading"},
            headers=auth_header(pm_token),
        )
        assert resp.status_code == 409, resp.text
        assert _strategy_status(strategy_id) == "Deprecated"
    finally:
        cleanup_user(pm_user_id)
        _cleanup(user_id, account_id, strategy_id)


def test_promote_to_paper_trading_succeeds_after_a_real_approval():
    # AC3: re-applying /promote after an unrelated status change is not blocked once a real
    # approval exists on record.
    user_id, account_id, strategy_id = _seed_strategy("Backtesting")
    _add_approval_request(strategy_id, "approved")
    sa_user_id, sa_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        resp = client.post(
            f"/api/v1/strategies/{strategy_id}/promote",
            json={"to_status": "PaperTrading"},
            headers=auth_header(sa_token),
        )
        assert resp.status_code == 200, resp.text
        assert _strategy_status(strategy_id) == "PaperTrading"
    finally:
        cleanup_user(sa_user_id)
        _cleanup(user_id, account_id, strategy_id)


def test_non_paper_trading_promotions_are_unaffected():
    # AC5: this fix narrows exactly one transition; Backtesting/Live/Deprecated targets keep
    # today's behaviour with no approval required.
    user_id, account_id, strategy_id = _seed_strategy("Coding")
    sa_user_id, sa_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        resp = client.post(
            f"/api/v1/strategies/{strategy_id}/promote",
            json={"to_status": "Backtesting"},
            headers=auth_header(sa_token),
        )
        assert resp.status_code == 200, resp.text
        assert _strategy_status(strategy_id) == "Backtesting"
    finally:
        cleanup_user(sa_user_id)
        _cleanup(user_id, account_id, strategy_id)
