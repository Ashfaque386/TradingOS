"""REL-010 E10.8d: Orchestrator retry endpoint (POST /agents/runs/{id}/retry) against the real
FastAPI app + real Postgres.

`retry` is real dispatched via the same detached `threading.Thread` machinery as
`/research/trigger` (src/api/routers/agents.py) -- every real LLM call that machinery would make
is exactly the kind of thing this codebase's existing test suite deliberately never exercises
over HTTP. `threading.Thread` itself is patched here so the retry endpoint's real DB writes (new
AgentRun row, `retried_from_run_id`) are exercised without spawning an actual real graph run.

The run-level `approve` / `reject` handlers were removed in US3 (BUG-B): a deployment
recommendation now opens a real `ApprovalRequest` and the decision is made via
`/api/v1/organization/approvals/{id}/approve|reject` -- covered by test_org_approval_gate.py.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api.main import app
from src.core.db import get_session
from src.core.security import ROLE_READ_ONLY_AUDITOR, ROLE_RISK_MANAGER
from src.models.agent import AgentRun
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
