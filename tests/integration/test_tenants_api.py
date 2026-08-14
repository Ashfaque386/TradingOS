"""Multi-tenant context API integration test (REL-064, API-015): src/api/routers/tenants.py
against the real FastAPI app + real Postgres. Proves real cross-tenant isolation, not just a
response-shape check -- two real tenants, real accounts seeded under each, confirming
GET /tenants/{id}/context only ever reports its own tenant's data.
"""

import uuid
from decimal import Decimal

from fastapi.testclient import TestClient

from src.api.main import app
from src.core.db import get_session
from src.core.security import (
    ROLE_PORTFOLIO_MANAGER,
    ROLE_READ_ONLY_AUDITOR,
    ROLE_SYSTEM_ADMINISTRATOR,
)
from src.models.account import Account
from src.models.tenant import Tenant
from src.models.user import User
from tests.auth_helpers import auth_header, cleanup_user, create_authenticated_user

client = TestClient(app)


def _create_tenant(admin_token: str, name: str) -> uuid.UUID:
    response = client.post("/api/v1/tenants", json={"name": name}, headers=auth_header(admin_token))
    assert response.status_code == 201
    return uuid.UUID(response.json()["id"])


def _seed_account(tenant_id: uuid.UUID, user_id: uuid.UUID, capital: str) -> uuid.UUID:
    account_id = uuid.uuid4()
    with get_session() as session:
        session.add(
            Account(
                id=account_id,
                user_id=user_id,
                tenant_id=tenant_id,
                broker="Zerodha",
                account_type="Live",
                capital_allocated=Decimal(capital),
            )
        )
        session.commit()
    return account_id


def _cleanup_accounts(account_ids: list[uuid.UUID]) -> None:
    if not account_ids:
        return
    with get_session() as session:
        session.query(Account).filter(Account.id.in_(account_ids)).delete(synchronize_session=False)
        session.commit()


def _cleanup_tenants(tenant_ids: list[uuid.UUID]) -> None:
    if not tenant_ids:
        return
    with get_session() as session:
        session.query(Tenant).filter(Tenant.id.in_(tenant_ids)).delete(synchronize_session=False)
        session.commit()


def _cleanup(*, tenant_ids: list[uuid.UUID], account_ids: list[uuid.UUID]) -> None:
    # Accounts reference both users and tenants -- always drop them first.
    _cleanup_accounts(account_ids)
    _cleanup_tenants(tenant_ids)


def test_create_tenant_requires_system_administrator():
    non_admin_id, non_admin_token = create_authenticated_user(ROLE_READ_ONLY_AUDITOR)
    try:
        response = client.post(
            "/api/v1/tenants",
            json={"name": "unauthorized-tenant"},
            headers=auth_header(non_admin_token),
        )
        assert response.status_code == 403
    finally:
        cleanup_user(non_admin_id)


def test_get_context_requires_authentication():
    response = client.get(f"/api/v1/tenants/{uuid.uuid4()}/context")
    assert response.status_code == 401


def test_get_context_404s_for_an_unknown_tenant():
    admin_id, admin_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        response = client.get(
            f"/api/v1/tenants/{uuid.uuid4()}/context", headers=auth_header(admin_token)
        )
        assert response.status_code == 404
    finally:
        cleanup_user(admin_id)


def test_two_tenants_are_genuinely_isolated_from_each_other():
    admin_id, admin_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    marker = uuid.uuid4().hex[:8]
    tenant_a = tenant_b = None
    account_a = account_b = None
    try:
        tenant_a = _create_tenant(admin_token, f"tenant-a-{marker}")
        tenant_b = _create_tenant(admin_token, f"tenant-b-{marker}")

        account_a = _seed_account(tenant_a, admin_id, "100000.00")
        account_b = _seed_account(tenant_b, admin_id, "999999.00")

        response = client.get(
            f"/api/v1/tenants/{tenant_a}/context", headers=auth_header(admin_token)
        )
        assert response.status_code == 200
        body = response.json()
        assert body["tenant_id"] == str(tenant_a)
        assert body["capital_pool"] == 100000.00
        sub_account_ids = {a["id"] for a in body["sub_accounts"]}
        assert str(account_a) in sub_account_ids
        assert str(account_b) not in sub_account_ids, "tenant B's account leaked into tenant A"
    finally:
        cleanup_ids = [i for i in (tenant_a, tenant_b) if i is not None]
        account_ids = [i for i in (account_a, account_b) if i is not None]
        if cleanup_ids or account_ids:
            _cleanup(tenant_ids=cleanup_ids, account_ids=account_ids)
        cleanup_user(admin_id)


def test_get_context_reports_real_members_and_only_active_accounts_in_the_capital_pool():
    admin_id, admin_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    marker = uuid.uuid4().hex[:8]
    tenant_id = None
    active_account = inactive_account = None
    try:
        tenant_id = _create_tenant(admin_token, f"tenant-members-{marker}")
        with get_session() as session:
            user = session.get(User, admin_id)
            assert user is not None
            user.tenant_id = tenant_id
            session.commit()

        active_account = _seed_account(tenant_id, admin_id, "50000.00")
        inactive_account = uuid.uuid4()
        with get_session() as session:
            session.add(
                Account(
                    id=inactive_account,
                    user_id=admin_id,
                    tenant_id=tenant_id,
                    broker="Zerodha",
                    account_type="Live",
                    capital_allocated=Decimal("25000.00"),
                    is_active=False,
                )
            )
            session.commit()

        response = client.get(
            f"/api/v1/tenants/{tenant_id}/context", headers=auth_header(admin_token)
        )
        assert response.status_code == 200
        body = response.json()
        assert body["capital_pool"] == 50000.00, "inactive account must not count in capital_pool"
        member_ids = {m["id"] for m in body["members"]}
        assert str(admin_id) in member_ids
    finally:
        # This test moved the admin user onto the new tenant (user.tenant_id = tenant_id), so
        # the user row must be deleted before the tenant row, not after -- the reverse of every
        # other test here, which never touches an existing user's tenant_id.
        account_ids = [i for i in (active_account, inactive_account) if i is not None]
        _cleanup_accounts(account_ids)
        cleanup_user(admin_id)
        _cleanup_tenants([tenant_id] if tenant_id is not None else [])


def test_portfolio_manager_can_also_read_context():
    pm_id, pm_token = create_authenticated_user(ROLE_PORTFOLIO_MANAGER)
    admin_id, admin_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    tenant_id = None
    try:
        tenant_id = _create_tenant(admin_token, f"tenant-pm-{uuid.uuid4().hex[:8]}")
        response = client.get(f"/api/v1/tenants/{tenant_id}/context", headers=auth_header(pm_token))
        assert response.status_code == 200
    finally:
        if tenant_id is not None:
            _cleanup(tenant_ids=[tenant_id], account_ids=[])
        cleanup_user(pm_id)
        cleanup_user(admin_id)
