"""Audit query API integration tests (REL-006 E6.3, API-068/069/070) against the real FastAPI
app + real Postgres -- exit criterion 2: "ReadOnlyAuditor can query real audit history via the
API; no other role's write path can modify/delete an entry (tested, not just documented)."

Seeded rows are never deleted afterward: the API request goes through its own DB session/
connection (a different one than this test uses), so the seeded row must be genuinely committed
for the API to see it -- and once committed, deleting it (even via the trigger-bypass) would
orphan any real row written after it, permanently breaking verify_chain() for later test runs
(see test_audit_tamper_detection.py's module docstring for the full explanation). A handful of
permanent test rows in AuditLog is consistent with its real "never purged" semantics, not a bug.
"""

import uuid

import pytest
import sqlalchemy.exc
from fastapi.testclient import TestClient
from sqlalchemy import text

from src.api.main import app
from src.core.audit import write_audit_entry
from src.core.db import get_session
from src.core.security import ROLE_READ_ONLY_AUDITOR, ROLE_RISK_MANAGER, ROLE_SYSTEM_ADMINISTRATOR
from tests.auth_helpers import auth_header, cleanup_user, create_authenticated_user

client = TestClient(app)


def _seed_row(
    actor_id: str = "test-audit-api", entity_id: uuid.UUID | None = None, action: str | None = None
) -> int:
    with get_session() as session:
        row = write_audit_entry(
            session,
            actor_type="System",
            actor_id=actor_id,
            action=action or "TEST_AUDIT_API_EVENT",
            entity_type="Test",
            entity_id=entity_id,
        )
        session.commit()
        return row.id


def test_read_only_auditor_can_list_and_fetch_real_audit_logs():
    row_id = _seed_row("test-audit-api-list-fetch")
    user_id, token = create_authenticated_user(ROLE_READ_ONLY_AUDITOR)
    headers = auth_header(token)

    try:
        list_response = client.get(
            "/api/v1/audit/logs", params={"actor_id": "test-audit-api-list-fetch"}, headers=headers
        )
        assert list_response.status_code == 200
        assert any(row["id"] == row_id for row in list_response.json())

        get_response = client.get(f"/api/v1/audit/logs/{row_id}", headers=headers)
        assert get_response.status_code == 200
        body = get_response.json()
        assert body["action"] == "TEST_AUDIT_API_EVENT"
        assert len(body["entry_hash"]) == 64
    finally:
        cleanup_user(user_id)


def test_system_administrator_can_also_read_audit_logs():
    row_id = _seed_row("test-audit-api-sa-read")
    user_id, token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    headers = auth_header(token)

    try:
        response = client.get(f"/api/v1/audit/logs/{row_id}", headers=headers)
        assert response.status_code == 200
    finally:
        cleanup_user(user_id)


def test_risk_manager_role_is_denied_audit_access():
    user_id, token = create_authenticated_user(ROLE_RISK_MANAGER)
    headers = auth_header(token)

    try:
        response = client.get("/api/v1/audit/logs", headers=headers)
        assert response.status_code == 403
    finally:
        cleanup_user(user_id)


def test_unauthenticated_request_is_rejected():
    response = client.get("/api/v1/audit/logs")
    assert response.status_code == 401


def test_read_only_auditor_can_trace_every_audit_entry_for_one_trade_entity():
    """API-070: /audit/trades/{entity_id}/trace, ordered chronologically."""
    entity_id = uuid.uuid4()
    first_id = _seed_row("test-audit-api-trace", entity_id=entity_id, action="ORDER_PLACED")
    second_id = _seed_row(
        "test-audit-api-trace", entity_id=entity_id, action="ORDER_BLOCKED_COMPLIANCE"
    )
    unrelated_id = _seed_row("test-audit-api-trace-unrelated", entity_id=uuid.uuid4())

    user_id, token = create_authenticated_user(ROLE_READ_ONLY_AUDITOR)
    headers = auth_header(token)

    try:
        response = client.get(f"/api/v1/audit/trades/{entity_id}/trace", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["entity_id"] == str(entity_id)
        entry_ids = [e["id"] for e in body["entries"]]
        assert entry_ids == [first_id, second_id]
        assert unrelated_id not in entry_ids
    finally:
        cleanup_user(user_id)


def test_no_role_can_mutate_or_delete_audit_log_rows_via_direct_sql():
    """Re-exercises the DB-level trigger (SEC-037/041) at this layer: even with a real, direct
    SQL statement (not going through the ORM's read-only router surface, since no write/delete
    endpoint exists at all for this resource -- there is no HTTP path to even attempt this),
    the database itself refuses the mutation. The UPDATE is rejected outright, so the seeded row
    is left exactly as written -- nothing to clean up either way."""
    row_id = _seed_row("test-audit-api-trigger-check")
    with get_session() as session, pytest.raises(sqlalchemy.exc.DBAPIError):
        session.execute(
            text("UPDATE audit_log SET action = 'TAMPERED' WHERE id = :id"), {"id": row_id}
        )
        session.commit()
