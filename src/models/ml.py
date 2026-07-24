from typing import Any

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, UUIDPKMixin


class MLModel(Base, UUIDPKMixin, TimestampMixin):
    """DB-017. MLflow model registry pointer table."""

    __tablename__ = "ml_models"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_type: Mapped[str] = mapped_column(String(30), nullable=False)
    mlflow_run_id: Mapped[str] = mapped_column(String(100), nullable=False)
    stage: Mapped[str] = mapped_column(String(20), nullable=False, default="Staging")
    git_commit_hash: Mapped[str | None] = mapped_column(String(40))
    training_data_hash: Mapped[str | None] = mapped_column(String(64))
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    artifact_path: Mapped[str] = mapped_column(String(255), nullable=False)
