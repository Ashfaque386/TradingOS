"""REL-060 (API-020/021): pause/resume mechanism against the real LangGraph checkpointer + real
Postgres -- confirms a paused run's exact execution position survives across two separate
`_execute_graph_run` calls (simulating a pause in one background thread, a resume in a later
one), not just that the REST endpoints flip a status flag.

Every graph node is mocked (reusing tests/unit/test_graph.py's own `_mock_pipeline` fixture,
matching this codebase's own established cross-file test-helper precedent, e.g.
test_audit_chain_monitor.py importing from test_audit_tamper_detection.py) -- this proves the
checkpoint/pause/resume MECHANISM, not node business logic, which the rest of the suite already
covers. The mocked pipeline is routed through a real compliance Block so the run reaches END
right after `compliance` -- deliberately avoiding python_validator/backtesting, which would
otherwise trigger the real sandbox pipeline (a ~20s cold start, per REL-032) as a side effect of
`_persist_strategy_progress`'s own real, unmocked persistence logic.
"""

import uuid
from contextlib import ExitStack
from datetime import UTC, datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.agents.state import ComplianceVerdict
from src.api.main import app
from src.api.routers.agents import _execute_graph_run
from src.core.db import get_session
from src.core.security import ROLE_READ_ONLY_AUDITOR, ROLE_RISK_MANAGER
from src.models.agent import AgentLog, AgentRun
from tests.auth_helpers import auth_header, cleanup_user, create_authenticated_user
from tests.unit.test_graph import _DIRECTIVE, _mock_pipeline

client = TestClient(app)

_BLOCK_VERDICT = ComplianceVerdict(
    verdict="Block",
    violations=["TEST_ONLY_BLOCK"],
    naked_options_checked=False,
    position_limit_checked=False,
    circuit_filter_checked=False,
    narrative="deliberately blocked so this test never reaches the real sandbox/backtest",
)


def _never_called_validator(state: object) -> dict[str, object]:
    raise AssertionError("python_validator must never run past a real compliance Block")


def _seed_root_run() -> tuple[uuid.UUID, str]:
    thread_id = str(uuid.uuid4())
    with get_session() as session:
        root = AgentRun(
            graph_thread_id=thread_id,
            agent_name="TradingOSGraph",
            status="Running",
            started_at=datetime.now(UTC),
        )
        session.add(root)
        session.commit()
        return root.id, thread_id


def _cleanup_run(thread_id: str) -> None:
    with get_session() as session:
        run_ids = [
            r.id for r in session.query(AgentRun.id).filter(AgentRun.graph_thread_id == thread_id)
        ]
        session.query(AgentLog).filter(AgentLog.agent_run_id.in_(run_ids)).delete(
            synchronize_session=False
        )
        session.query(AgentRun).filter(AgentRun.graph_thread_id == thread_id).delete(
            synchronize_session=False
        )
        session.commit()


def test_pause_after_one_node_then_resume_runs_only_the_remaining_nodes_once():
    root_id, thread_id = _seed_root_run()
    call_counts: dict[str, int] = {}

    def _counted(name: str, result: dict[str, object]):
        def _fn(state: object) -> dict[str, object]:
            call_counts[name] = call_counts.get(name, 0) + 1
            if name == "ceo_agent":
                # Deterministically request a pause right after the FIRST node completes --
                # avoids any real thread timing/polling to make this test reliable.
                with get_session() as session:
                    run = session.get(AgentRun, root_id)
                    assert run is not None
                    run.pause_requested = True
                    session.commit()
            return result

        return _fn

    patches = _mock_pipeline(
        validator_side_effect=_never_called_validator,
        ceo_side_effect=_counted(
            "ceo_agent", {"research_directive": _DIRECTIVE, "strategy_rejection_count": 0}
        ),
        compliance_side_effect=_counted("compliance", {"compliance_verdict": _BLOCK_VERDICT}),
    )
    # market_analyst/strategy_generator/options_strategy_agent/python_code_generator keep
    # _mock_pipeline's own default return_value -- only ceo_agent (the pause point) and
    # compliance (the last node before this test's real Block routes straight to END) need
    # their own call counts tracked to prove the mechanism.

    try:
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            _execute_graph_run(thread_id=thread_id, root_run_id=root_id, resume=False)

        with get_session() as session:
            root = session.get(AgentRun, root_id)
            assert root is not None
            assert root.status == "Paused"
            assert root.pause_requested is False
            assert root.tracking_snapshot is not None

        assert call_counts.get("ceo_agent") == 1
        assert call_counts.get("compliance") is None  # never reached before the pause

        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            _execute_graph_run(thread_id=thread_id, root_run_id=root_id, resume=True)

        assert call_counts.get("ceo_agent") == 1  # not re-run on resume
        assert call_counts.get("compliance") == 1

        with get_session() as session:
            root = session.get(AgentRun, root_id)
            assert root is not None
            assert root.status == "Completed"
            assert root.tracking_snapshot is None
    finally:
        _cleanup_run(thread_id)


def test_pause_requires_the_gated_role():
    root_id, thread_id = _seed_root_run()
    user_id, token = create_authenticated_user(ROLE_READ_ONLY_AUDITOR)
    try:
        response = client.post(f"/api/v1/agents/runs/{root_id}/pause", headers=auth_header(token))
        assert response.status_code == 403
    finally:
        cleanup_user(user_id)
        _cleanup_run(thread_id)


def test_pause_404s_for_an_unknown_run():
    user_id, token = create_authenticated_user(ROLE_RISK_MANAGER)
    try:
        response = client.post(
            f"/api/v1/agents/runs/{uuid.uuid4()}/pause", headers=auth_header(token)
        )
        assert response.status_code == 404
    finally:
        cleanup_user(user_id)


def test_pause_400s_for_a_run_that_is_not_running():
    root_id, thread_id = _seed_root_run()
    with get_session() as session:
        run = session.get(AgentRun, root_id)
        assert run is not None
        run.status = "Completed"
        session.commit()

    user_id, token = create_authenticated_user(ROLE_RISK_MANAGER)
    try:
        response = client.post(f"/api/v1/agents/runs/{root_id}/pause", headers=auth_header(token))
        assert response.status_code == 400
    finally:
        cleanup_user(user_id)
        _cleanup_run(thread_id)


def test_pause_sets_the_real_flag_without_dispatching_a_thread():
    root_id, thread_id = _seed_root_run()
    user_id, token = create_authenticated_user(ROLE_RISK_MANAGER)
    try:
        response = client.post(f"/api/v1/agents/runs/{root_id}/pause", headers=auth_header(token))
        assert response.status_code == 200
        body = response.json()
        assert body["run_id"] == str(root_id)
        assert body["status"] == "Running"  # the flip to Paused happens async, in the thread

        with get_session() as session:
            run = session.get(AgentRun, root_id)
            assert run is not None
            assert run.pause_requested is True
    finally:
        cleanup_user(user_id)
        _cleanup_run(thread_id)


def test_resume_requires_the_gated_role():
    root_id, thread_id = _seed_root_run()
    user_id, token = create_authenticated_user(ROLE_READ_ONLY_AUDITOR)
    try:
        response = client.post(f"/api/v1/agents/runs/{root_id}/resume", headers=auth_header(token))
        assert response.status_code == 403
    finally:
        cleanup_user(user_id)
        _cleanup_run(thread_id)


def test_resume_404s_for_an_unknown_run():
    user_id, token = create_authenticated_user(ROLE_RISK_MANAGER)
    try:
        response = client.post(
            f"/api/v1/agents/runs/{uuid.uuid4()}/resume", headers=auth_header(token)
        )
        assert response.status_code == 404
    finally:
        cleanup_user(user_id)


def test_resume_400s_for_a_run_that_is_not_paused():
    root_id, thread_id = _seed_root_run()  # seeded as "Running", not "Paused"
    user_id, token = create_authenticated_user(ROLE_RISK_MANAGER)
    try:
        response = client.post(f"/api/v1/agents/runs/{root_id}/resume", headers=auth_header(token))
        assert response.status_code == 400
    finally:
        cleanup_user(user_id)
        _cleanup_run(thread_id)


@patch("src.api.routers.agents.threading.Thread")
def test_resume_dispatches_a_real_background_thread(mock_thread):
    root_id, thread_id = _seed_root_run()
    with get_session() as session:
        run = session.get(AgentRun, root_id)
        assert run is not None
        run.status = "Paused"
        session.commit()

    user_id, token = create_authenticated_user(ROLE_RISK_MANAGER)
    try:
        response = client.post(f"/api/v1/agents/runs/{root_id}/resume", headers=auth_header(token))
        assert response.status_code == 202
        assert response.json()["status"] == "Running"

        mock_thread.assert_called_once()
        _, kwargs = mock_thread.call_args
        assert kwargs["kwargs"]["resume"] is True
        assert kwargs["kwargs"]["root_run_id"] == root_id
        mock_thread.return_value.start.assert_called_once()

        with get_session() as session:
            run = session.get(AgentRun, root_id)
            assert run is not None
            assert run.status == "Running"
    finally:
        cleanup_user(user_id)
        _cleanup_run(thread_id)
