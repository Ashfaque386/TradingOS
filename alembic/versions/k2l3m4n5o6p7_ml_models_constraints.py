"""add real CHECK constraint + composite index to ml_models (REL-008 E8.6 follow-up)

Revision ID: k2l3m4n5o6p7
Revises: j1k2l3m4n5o6
Create Date: 2026-07-28 08:00:00.000000

Real gap found during REL-008 planning: Phase_11_Database_Design.md's DB-017 spec describes a
`model_type IN ('LightGBM','TFT-PyTorch','PPO-RL','SAC-RL')` CHECK constraint, but the original
migration (6cd568130517_initial_schema.py) never actually created it -- `model_type` has always
been a plain, unvalidated VARCHAR(30). REL-008 is the first code path to ever write a real
ml_models row, so this is the first time the gap has mattered. Also adds a composite
(model_type, stage) index -- the real hot lookup every promote/evaluate/drift-check call makes
("the current Production model of type X").
"""

from collections.abc import Sequence

from alembic import op

revision: str = "k2l3m4n5o6p7"
down_revision: str | Sequence[str] | None = "j1k2l3m4n5o6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_ml_models_model_type",
        "ml_models",
        "model_type IN ('LightGBM','TFT-PyTorch','PPO-RL','SAC-RL')",
    )
    op.create_index("ix_ml_models_type_stage", "ml_models", ["model_type", "stage"])


def downgrade() -> None:
    op.drop_index("ix_ml_models_type_stage", table_name="ml_models")
    op.drop_constraint("ck_ml_models_model_type", "ml_models", type_="check")
