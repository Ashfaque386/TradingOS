"""add ON DELETE CASCADE to risk_limits.set_by_user_id (REL-007 E7.4 follow-up)

Revision ID: j1k2l3m4n5o6
Revises: i0j1k2l3m4n5
Create Date: 2026-07-26 16:30:00.000000

Pre-existing gap from the original REL-004 schema (6cd568130517), never exercised until E7.4
became the first code path in this codebase to ever create a real RiskLimit row: a real
ForeignKeyViolation surfaced in the E7.4 integration test suite (not anticipated in advance) --
tests/auth_helpers.py::cleanup_user() hard-deletes User rows, which any test creating a real
RiskLimit now does transitively via the confirm endpoint. Same fix, same reasoning, as
g7h8i9j0k1l2 (mfa_backup_codes) and i0j1k2l3m4n5 (risk_limit_change_requests): production never
hard-deletes a User, so this only matters for test cleanup.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "j1k2l3m4n5o6"
down_revision: Union[str, None] = "i0j1k2l3m4n5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CONSTRAINT_NAME = "risk_limits_set_by_user_id_fkey"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT_NAME, "risk_limits", type_="foreignkey")
    op.create_foreign_key(
        _CONSTRAINT_NAME, "risk_limits", "users", ["set_by_user_id"], ["id"], ondelete="CASCADE"
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT_NAME, "risk_limits", type_="foreignkey")
    op.create_foreign_key(_CONSTRAINT_NAME, "risk_limits", "users", ["set_by_user_id"], ["id"])
