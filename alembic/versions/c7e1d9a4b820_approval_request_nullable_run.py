"""approval_requests.run_id nullable (spec 001-ceo-led-trading-org, US3 / T045).

A deployment recommendation from the legacy research graph opens the same real human approval
gate, but has no ``OrganizationRun`` to point at. Relax the NOT NULL so both the org-led path
(sets ``run_id``) and the legacy path (leaves it null) can create an ``ApprovalRequest``.

Revision ID: c7e1d9a4b820
Revises: eb7e9528f695
Create Date: 2026-09-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c7e1d9a4b820"
down_revision: str | None = "eb7e9528f695"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("approval_requests", "run_id", nullable=True)


def downgrade() -> None:
    op.alter_column("approval_requests", "run_id", nullable=False)
