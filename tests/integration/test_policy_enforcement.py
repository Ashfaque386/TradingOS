"""REL-007 E7.5: real HTTP coverage for the 3 require_role-gated endpoints that had zero
integration test coverage before this epic (confirmed by grep across tests/integration/ prior to
this file existing) -- audit.py's GET routes, strategies.py's promote, and settings.py's
notification-channel mutations. Exercises the real Casbin-backed require_role() end-to-end, not
just src/core/policy.py's enforcer in isolation (see tests/unit/test_policy.py for that).
"""

import uuid

from fastapi.testclient import TestClient

from src.api.main import app
from src.core.db import get_session
from src.core.security import (
    ROLE_PORTFOLIO_MANAGER,
    ROLE_READ_ONLY_AUDITOR,
    ROLE_SYSTEM_ADMINISTRATOR,
)
from src.models.user import NotificationChannel
from tests.auth_helpers import auth_header, cleanup_user, create_authenticated_user

client = TestClient(app)


def test_audit_logs_get_is_readable_by_sa_and_auditor_but_not_others():
    admin_id, admin_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    auditor_id, auditor_token = create_authenticated_user(ROLE_READ_ONLY_AUDITOR)
    pm_id, pm_token = create_authenticated_user(ROLE_PORTFOLIO_MANAGER)
    try:
        no_token = client.get("/api/v1/audit/logs")
        as_admin = client.get("/api/v1/audit/logs", headers=auth_header(admin_token))
        as_auditor = client.get("/api/v1/audit/logs", headers=auth_header(auditor_token))
        as_pm = client.get("/api/v1/audit/logs", headers=auth_header(pm_token))

        assert no_token.status_code == 401
        assert as_admin.status_code == 200
        assert as_auditor.status_code == 200
        assert as_pm.status_code == 403
    finally:
        cleanup_user(admin_id)
        cleanup_user(auditor_id)
        cleanup_user(pm_id)


def test_strategy_promote_is_gated_by_role_before_reaching_the_not_found_check():
    admin_id, admin_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    auditor_id, auditor_token = create_authenticated_user(ROLE_READ_ONLY_AUDITOR)
    fake_strategy_id = uuid.uuid4()
    try:
        no_token = client.post(
            f"/api/v1/strategies/{fake_strategy_id}/promote", json={"to_status": "Live"}
        )
        wrong_role = client.post(
            f"/api/v1/strategies/{fake_strategy_id}/promote",
            json={"to_status": "Live"},
            headers=auth_header(auditor_token),
        )
        right_role = client.post(
            f"/api/v1/strategies/{fake_strategy_id}/promote",
            json={"to_status": "Live"},
            headers=auth_header(admin_token),
        )

        assert no_token.status_code == 401
        assert wrong_role.status_code == 403
        # Past the role gate, rejected downstream because this strategy doesn't exist -- proves
        # the gate itself let the right role through, not that the whole endpoint is broken.
        assert right_role.status_code == 404
    finally:
        cleanup_user(admin_id)
        cleanup_user(auditor_id)


def test_notification_channel_mutation_is_gated_by_role():
    admin_id, admin_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    auditor_id, auditor_token = create_authenticated_user(ROLE_READ_ONLY_AUDITOR)
    created_channel_id = None
    try:
        no_token = client.post(
            "/api/v1/settings/notification-channels",
            json={"channel_type": "Telegram", "external_handle": "@test"},
        )
        wrong_role = client.post(
            "/api/v1/settings/notification-channels",
            json={"channel_type": "Telegram", "external_handle": "@test"},
            headers=auth_header(auditor_token),
        )
        right_role = client.post(
            "/api/v1/settings/notification-channels",
            json={"channel_type": "Telegram", "external_handle": "@test"},
            headers=auth_header(admin_token),
        )

        assert no_token.status_code == 401
        assert wrong_role.status_code == 403
        assert right_role.status_code == 201
        created_channel_id = right_role.json()["id"]
    finally:
        cleanup_user(admin_id)
        cleanup_user(auditor_id)
        if created_channel_id is not None:
            with get_session() as session:
                session.query(NotificationChannel).filter(
                    NotificationChannel.id == uuid.UUID(created_channel_id)
                ).delete()
                session.commit()
