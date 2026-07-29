"""add risk_limit_change_requests table (REL-007 E7.4, SEC-013/041)

Revision ID: i0j1k2l3m4n5
Revises: h9i0j1k2l3m4
Create Date: 2026-07-26 16:00:00.000000

See src/models/risk_limit_change_request.py's docstring for the dual-control design.

`ondelete="CASCADE"` on the two user FKs -- same reasoning already established for
mfa_backup_codes (g7h8i9j0k1l2): production never hard-deletes a User row (soft-delete via
is_active), so this only matters for test cleanup, and without it a real ForeignKeyViolation
breaks tests/auth_helpers.py::cleanup_user() the moment a test stages a real change request
(found the same way as the MFA case -- a real test failure, not anticipated in advance). The
compliance-relevant permanent record is the hash-chained AuditLog row written alongside every
stage/confirm/reject (src/api/routers/risk_limits.py), which is keyed by actor email string, not
a FK -- unaffected by this table's rows being cascade-deleted.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "i0j1k2l3m4n5"
down_revision: Union[str, None] = "h9i0j1k2l3m4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "risk_limit_change_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope_type", sa.String(length=20), nullable=False),
        sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("max_daily_loss", sa.Numeric(18, 2), nullable=False),
        sa.Column("max_position_size_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("max_sector_exposure_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("max_drawdown_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("effective_from", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("staged_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("confirmed_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("resulting_risk_limit_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["staged_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["confirmed_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resulting_risk_limit_id"], ["risk_limits.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_risk_limit_change_requests_status", "risk_limit_change_requests", ["status"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_risk_limit_change_requests_status", table_name="risk_limit_change_requests"
    )
    op.drop_table("risk_limit_change_requests")
