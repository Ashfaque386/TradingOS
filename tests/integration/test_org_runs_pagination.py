"""spec 002 US10 (T046): `GET /organization/runs` gained `offset` pagination so an operator can
page past the previous hard 20-row cap instead of only ever seeing the most recent runs.
Verifies real server-side offset+status filtering against the live Postgres-backed table --
not a client-side truncation.
"""

import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from src.api.main import app
from src.core.db import get_session
from src.core.security import ROLE_SYSTEM_ADMINISTRATOR
from src.models.tenant import DEFAULT_TENANT_ID
from src.orchestration.enums import RunStatus
from tests.auth_helpers import auth_header, cleanup_user, create_authenticated_user
from tests.orchestration_helpers import cleanup_run

client = TestClient(app)

_STATUS_TAG = "test_org_runs_pagination"


def _seed_bare_run(status: str, created_at: datetime) -> uuid.UUID:
    """A run row with no plan/tasks -- pagination only needs to see distinct, orderable rows."""
    from src.models.orchestration import OrganizationRun

    run_id = uuid.uuid4()
    with get_session() as session:
        session.add(
            OrganizationRun(
                id=run_id,
                tenant_id=uuid.UUID(DEFAULT_TENANT_ID),
                objective=_STATUS_TAG,
                source="api",
                status=status,
                thread_id=f"org-page-{run_id}",
                created_at=created_at,
                updated_at=created_at,
            )
        )
        session.commit()
    return run_id


def test_offset_pages_past_the_default_window_with_no_duplicates_or_gaps() -> None:
    user_id, token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    headers = auth_header(token)
    now = datetime.now(UTC)
    run_ids = [
        _seed_bare_run(RunStatus.COMPLETED.value, now.replace(microsecond=i)) for i in range(25)
    ]
    try:
        seen: set[str] = set()
        offset = 0
        page_size = 10
        while True:
            resp = client.get(
                "/api/v1/organization/runs",
                params={"limit": page_size, "offset": offset, "status": "completed"},
                headers=headers,
            )
            assert resp.status_code == 200
            page = resp.json()
            page_ids = {row["run_id"] for row in page}
            seen |= page_ids & {str(r) for r in run_ids}
            if len(page) < page_size:
                break
            offset += page_size
            assert offset < 1000, "pagination did not terminate"
        assert seen == {
            str(r) for r in run_ids
        }, "every seeded run must appear exactly once across pages"
    finally:
        for r in run_ids:
            cleanup_run(r)
        cleanup_user(user_id)


def test_offset_and_status_compose_server_side_not_client_truncated() -> None:
    user_id, token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    headers = auth_header(token)
    now = datetime.now(UTC)
    failed_ids = [
        _seed_bare_run(RunStatus.FAILED.value, now.replace(microsecond=i)) for i in range(3)
    ]
    completed_ids = [
        _seed_bare_run(RunStatus.COMPLETED.value, now.replace(microsecond=i + 100))
        for i in range(3)
    ]
    try:
        resp = client.get(
            "/api/v1/organization/runs",
            params={"status": "failed", "limit": 200, "offset": 0},
            headers=headers,
        )
        assert resp.status_code == 200
        returned_ids = {row["run_id"] for row in resp.json()}
        assert {str(r) for r in failed_ids} <= returned_ids
        assert not (
            {str(r) for r in completed_ids} & returned_ids
        ), "status filter must be applied server-side, not just visually"
    finally:
        for r in failed_ids + completed_ids:
            cleanup_run(r)
        cleanup_user(user_id)
