from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, UUIDPKMixin

# REL-064: the one tenant every pre-existing row (and every table's real Postgres
# server_default) was backfilled/defaulted onto -- see alembic/versions/w4x5y6z7a8b9's own
# docstring for why a server_default exists at all (pre-existing test fixtures that construct
# User/Account/Strategy/Order rows directly, with no idea this column exists).
DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


class Tenant(Base, UUIDPKMixin, TimestampMixin):
    """REL-064 (API-015). A real organization/account-owner grouping -- `tenant_id` threads
    through `users`/`accounts`/`strategies`/`orders` (alembic/versions/w4x5y6z7a8b9). Every
    row created before this migration was backfilled onto one seeded "Primary Tenant" row, so
    the existing single-tenant system's behavior is unchanged; cross-tenant query isolation
    isn't retrofitted into every existing endpoint this pass -- only `GET /tenants/{id}/context`
    (the SRS's own literal API-015 row) reads this column."""

    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(150), nullable=False)
