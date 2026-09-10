"""HITL approval-gate integration test (spec T050, quickstart Scenario 3, SC-003, FR-052..057).

A deployment recommendation leaves the strategy in ``PendingPaperApproval`` behind a real
``ApprovalRequest``:

- pending is **not** Paper Trading, and nothing auto-transitions it (no timeout, FR-057);
- ``RiskManager`` cannot approve -> 403 + an audited ``RBAC_DENIED`` row (FR-053, clarify Q1);
- ``PortfolioManager`` approve -> ``PaperTrading`` + ``APPROVAL_APPROVED`` audit entry;
- reject without a reason -> 422; reject with a reason -> ``Deprecated``, never Paper;
- Paper -> Live stays the untouched existing ``/api/v1/strategies/{id}/promote`` gate (FR-055).
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from src.api.main import app
from src.core.db import get_session
from src.core.security import ROLE_PORTFOLIO_MANAGER, ROLE_RISK_MANAGER
from src.models.account import Account
from src.models.approval import ApprovalRequest
from src.models.audit import AuditLog
from src.models.strategy import Strategy, StrategyVersion
from src.models.user import User
from tests.auth_helpers import auth_header, cleanup_user, create_authenticated_user

client = TestClient(app)

_CODE = "def generate_signals(data):\n    return data"


def _seed_pending_approval() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """User -> Account -> Strategy(status='PendingPaperApproval') + StrategyVersion + a pending
    ApprovalRequest (run_id null: the legacy-graph path). Returns
    (user_id, account_id, strategy_id, approval_id)."""
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
                email=f"approval-gate-{user_id}@example.invalid",
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
            name="approval-gate-test-strategy",
            asset_class="Equity",
            style="Intraday",
            status="PendingPaperApproval",
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
    with get_session() as session:
        approval = ApprovalRequest(
            run_id=None,
            strategy_id=strategy_id,
            strategy_version_id=version_id,
            recommendation_artefact_id=None,
            status="pending",
            created_at=datetime.now(UTC),
        )
        session.add(approval)
        session.flush()
        approval_id = approval.id
        session.commit()
    return user_id, account_id, strategy_id, approval_id


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


def test_pending_is_not_paper_and_does_not_auto_transition():
    user_id, account_id, strategy_id, approval_id = _seed_pending_approval()
    try:
        assert _strategy_status(strategy_id) == "PendingPaperApproval"
        # No timeout / job ever moves it on its own (FR-057): re-read, still pending.
        with get_session() as session:
            req = session.get(ApprovalRequest, approval_id)
            assert req is not None and req.status == "pending"
        assert _strategy_status(strategy_id) == "PendingPaperApproval"
    finally:
        _cleanup(user_id, account_id, strategy_id)


def test_riskmanager_cannot_approve_and_the_denial_is_audited():
    user_id, account_id, strategy_id, approval_id = _seed_pending_approval()
    rm_user_id, rm_token = create_authenticated_user(ROLE_RISK_MANAGER)
    try:
        resp = client.post(
            f"/api/v1/organization/approvals/{approval_id}/approve",
            headers=auth_header(rm_token),
        )
        assert resp.status_code == 403
        assert _strategy_status(strategy_id) == "PendingPaperApproval"
        with get_session() as session:
            denials = session.scalars(
                select(AuditLog).where(AuditLog.action == "RBAC_DENIED")
            ).all()
            assert any(
                str(approval_id) in (d.after_state or {}).get("path", "") for d in denials
            ), "expected an audited RBAC_DENIED row for the approvals endpoint"
    finally:
        cleanup_user(rm_user_id)
        _cleanup(user_id, account_id, strategy_id)


def test_reject_without_a_reason_is_rejected_422():
    user_id, account_id, strategy_id, approval_id = _seed_pending_approval()
    pm_user_id, pm_token = create_authenticated_user(ROLE_PORTFOLIO_MANAGER)
    try:
        resp = client.post(
            f"/api/v1/organization/approvals/{approval_id}/reject",
            json={},
            headers=auth_header(pm_token),
        )
        assert resp.status_code == 422
        assert _strategy_status(strategy_id) == "PendingPaperApproval"
    finally:
        cleanup_user(pm_user_id)
        _cleanup(user_id, account_id, strategy_id)


def test_portfoliomanager_approve_moves_strategy_into_paper_trading():
    user_id, account_id, strategy_id, approval_id = _seed_pending_approval()
    pm_user_id, pm_token = create_authenticated_user(ROLE_PORTFOLIO_MANAGER)
    try:
        resp = client.post(
            f"/api/v1/organization/approvals/{approval_id}/approve",
            headers=auth_header(pm_token),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "approved"
        assert _strategy_status(strategy_id) == "PaperTrading"
        with get_session() as session:
            req = session.get(ApprovalRequest, approval_id)
            assert req is not None
            assert req.status == "approved"
            assert req.decided_by and req.decided_at is not None
            assert req.audit_reference is not None
            actions = session.scalars(
                select(AuditLog.action).where(AuditLog.entity_id == approval_id)
            ).all()
            assert "APPROVAL_APPROVED" in actions
    finally:
        cleanup_user(pm_user_id)
        _cleanup(user_id, account_id, strategy_id)


def test_reject_with_a_reason_deprecates_and_never_enters_paper():
    user_id, account_id, strategy_id, approval_id = _seed_pending_approval()
    pm_user_id, pm_token = create_authenticated_user(ROLE_PORTFOLIO_MANAGER)
    try:
        resp = client.post(
            f"/api/v1/organization/approvals/{approval_id}/reject",
            json={"reason": "Backtest Sharpe looks overfit on manual review."},
            headers=auth_header(pm_token),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "rejected"
        assert _strategy_status(strategy_id) == "Deprecated"
        with get_session() as session:
            req = session.get(ApprovalRequest, approval_id)
            assert req is not None and req.status == "rejected"
            assert req.reason == "Backtest Sharpe looks overfit on manual review."
        # A second decision on an already-decided request is refused, not re-applied.
        resp2 = client.post(
            f"/api/v1/organization/approvals/{approval_id}/approve",
            headers=auth_header(pm_token),
        )
        assert resp2 is not None and resp2.status_code == 409
    finally:
        cleanup_user(pm_user_id)
        _cleanup(user_id, account_id, strategy_id)


def test_paper_to_live_promote_gate_is_still_present():
    # FR-055: Paper -> Live stays the untouched existing gate, not part of the approvals flow.
    schema = client.get("/openapi.json").json()
    assert "/api/v1/strategies/{strategy_id}/promote" in schema["paths"]
    assert "post" in schema["paths"]["/api/v1/strategies/{strategy_id}/promote"]
