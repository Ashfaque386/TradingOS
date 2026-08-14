"""Multi-tenant context (REL-064, API-015): real multi-organization tenancy -- a genuine
`tenants` table with `tenant_id` threaded through `users`/`accounts`/`strategies`/`orders`
(alembic/versions/w4x5y6z7a8b9). Every row that existed before that migration was backfilled
onto one seeded "Primary Tenant," so the pre-existing single-tenant system's behavior is
unchanged; this router adds the one new capability the SRS's own API-015 row asks for --
resolving a tenant's real capital pool and sub-accounts -- plus the minimum `POST /tenants`
needed to make the table genuinely usable beyond that one seeded row. Cross-tenant query
isolation is NOT retrofitted into every other existing endpoint this pass -- see
src/models/tenant.py's own docstring for the explicit scope boundary.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from src.api.deps import require_role
from src.core.db import get_session
from src.core.security import ROLE_PORTFOLIO_MANAGER, ROLE_SYSTEM_ADMINISTRATOR
from src.models.account import Account
from src.models.tenant import Tenant
from src.models.user import User

router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])

_can_manage_tenants = require_role(ROLE_SYSTEM_ADMINISTRATOR, audit_denials=True)
_can_read_tenant_context = require_role(
    ROLE_SYSTEM_ADMINISTRATOR, ROLE_PORTFOLIO_MANAGER, audit_denials=True
)


class CreateTenantRequest(BaseModel):
    name: str


class TenantResponse(BaseModel):
    id: uuid.UUID
    name: str


@router.post("", response_model=TenantResponse, status_code=201)
def create_tenant(
    body: CreateTenantRequest, _user: User = Depends(_can_manage_tenants)
) -> TenantResponse:
    """SystemAdministrator-only -- the SRS's own API-015 row has no dedicated create verb, but
    without one this table would stay a permanent single row (the migration-seeded default
    tenant), which would make GET /tenants/{id}/context untestable as real multi-tenancy rather
    than a single-row read. Minimum necessary infrastructure, not scope creep."""
    with get_session() as session:
        tenant = Tenant(name=body.name)
        session.add(tenant)
        session.commit()
        session.refresh(tenant)
        return TenantResponse(id=tenant.id, name=tenant.name)


class SubAccountSummary(BaseModel):
    id: uuid.UUID
    broker: str
    account_type: str
    capital_allocated: float
    is_active: bool


class TenantMemberSummary(BaseModel):
    id: uuid.UUID
    email: str
    role: str


class TenantContextResponse(BaseModel):
    tenant_id: uuid.UUID
    name: str
    capital_pool: float
    sub_accounts: list[SubAccountSummary]
    members: list[TenantMemberSummary]


@router.get("/{tenant_id}/context", response_model=TenantContextResponse)
def get_tenant_context(
    tenant_id: uuid.UUID, _user: User = Depends(_can_read_tenant_context)
) -> TenantContextResponse:
    """API-015. Resolves the real multi-tenant context the SRS asks for: capital pool (the sum
    of every active account's capital_allocated under this tenant) and sub-accounts (the real
    Account rows themselves) -- plus members, the natural "who's in this tenant" extension of
    "context." Real isolation, not a shape-only read: an account under a different tenant_id
    never appears here, proven by test_tenants_api.py seeding two real tenants."""
    with get_session() as session:
        tenant = session.get(Tenant, tenant_id)
        if tenant is None:
            raise HTTPException(status_code=404, detail="Tenant not found")

        accounts = list(session.scalars(select(Account).where(Account.tenant_id == tenant_id)))
        members = list(session.scalars(select(User).where(User.tenant_id == tenant_id)))

        capital_pool = sum(a.capital_allocated for a in accounts if a.is_active)

        return TenantContextResponse(
            tenant_id=tenant.id,
            name=tenant.name,
            capital_pool=float(capital_pool),
            sub_accounts=[
                SubAccountSummary(
                    id=a.id,
                    broker=a.broker,
                    account_type=a.account_type,
                    capital_allocated=float(a.capital_allocated),
                    is_active=a.is_active,
                )
                for a in accounts
            ],
            members=[TenantMemberSummary(id=m.id, email=m.email, role=m.role) for m in members],
        )
