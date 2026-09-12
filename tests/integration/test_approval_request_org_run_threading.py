"""Follow-up to spec 002 US1: `ApprovalRequest.run_id` was always `None` in production because
no code path threaded a real `OrganizationRun.id` into `_open_paper_approval_request`
(`src/api/routers/agents.py`) -- even when the deployment recommendation came from an org-run-
driven task dispatch. This meant `approval.requested`/`approval.approved`/`approval.rejected`
could never actually reach the live `/organization` event bus, despite the underlying
approve/reject mechanism (Strategy.status transitions, audit log, RBAC) working correctly.

Fix: `org_run_id` is now threaded `_strategy_research_handler` (agent_invoker.py, via
`task.run_id`) -> `_execute_graph_run` -> `_persist_strategy_progress` ->
`_open_paper_approval_request`, which now accepts a real `run_id` instead of hardcoding `None`.
The legacy manually-triggered graph run (no `OrganizationRun`) is unaffected -- its three
`threading.Thread(target=_execute_graph_run, ...)` call sites never pass `org_run_id`, so it
still defaults to `None`, preserving today's behaviour there exactly.

This test exercises `_open_paper_approval_request` directly (the real function every caller
above eventually reaches) with a real `run_id`, proving both halves of the fix: the resulting
`ApprovalRequest` carries the real run id, and `approval.requested` is now actually observable
on the event bus for that run -- closing the gap discovered while implementing US1.
"""

import uuid
from decimal import Decimal

from src.api.routers.agents import _open_paper_approval_request
from src.core.db import get_session
from src.models.account import Account
from src.models.approval import ApprovalRequest
from src.models.orchestration import OrganizationalEvent
from src.models.strategy import Strategy, StrategyVersion
from src.models.user import User
from tests.auth_helpers import cleanup_user
from tests.orchestration_helpers import cleanup_run, seed_run_with_tasks

_CODE = "def generate_signals(data):\n    return data"


def _seed_strategy() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
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
                email=f"org-run-approval-{user_id}@example.invalid",
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
            name="org-run-approval-test-strategy",
            asset_class="Equity",
            style="Intraday",
            status="Backtesting",
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
    return user_id, account_id, strategy_id, version_id


def _cleanup_strategy(user_id: uuid.UUID, account_id: uuid.UUID, strategy_id: uuid.UUID) -> None:
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


def test_org_run_driven_approval_request_carries_a_real_run_id_and_emits_an_event():
    run_id, _task_ids = seed_run_with_tasks(
        [{"key": "deploy", "capability": "strategy_research", "assigned_agent": "deployment"}]
    )
    user_id, account_id, strategy_id, version_id = _seed_strategy()
    try:
        with get_session() as session:
            strategy = session.get(Strategy, strategy_id)
            assert strategy is not None
            _open_paper_approval_request(
                session,
                strategy=strategy,
                strategy_version_id=version_id,
                rationale="org-run-driven test recommendation",
                run_id=run_id,
            )
            session.commit()

        with get_session() as session:
            request = session.query(ApprovalRequest).filter_by(strategy_id=strategy_id).one()
            assert request.run_id == run_id, "ApprovalRequest must carry the real OrgRun id"

            events = (
                session.query(OrganizationalEvent)
                .filter(
                    OrganizationalEvent.run_id == run_id,
                    OrganizationalEvent.event_type == "approval.requested",
                )
                .all()
            )
            assert len(events) == 1, "approval.requested must now be observable on the event bus"
            assert events[0].subject_id == request.id
    finally:
        _cleanup_strategy(user_id, account_id, strategy_id)
        cleanup_run(run_id)


def test_legacy_manually_triggered_approval_request_still_has_a_null_run_id():
    # The manual trigger_research/resume paths never pass org_run_id -- confirms the default
    # (None) preserves exactly today's pre-fix behaviour for that path, no regression.
    user_id, account_id, strategy_id, version_id = _seed_strategy()
    try:
        with get_session() as session:
            strategy = session.get(Strategy, strategy_id)
            assert strategy is not None
            _open_paper_approval_request(
                session,
                strategy=strategy,
                strategy_version_id=version_id,
                rationale="legacy-path test recommendation",
            )
            session.commit()

        with get_session() as session:
            request = session.query(ApprovalRequest).filter_by(strategy_id=strategy_id).one()
            assert request.run_id is None
    finally:
        _cleanup_strategy(user_id, account_id, strategy_id)
