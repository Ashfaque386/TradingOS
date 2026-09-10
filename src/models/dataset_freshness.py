"""DatasetFreshnessRecord -- per required dataset (spec T009, data-model.md §11, FR-060..064).

An ingestion run sets ``status = fresh`` only if the data passed checksum validation (FR-064);
a failed/corrupt ingestion sets ``failed`` / ``unavailable`` and raises an alert. The planner
reads this before dispatching a dataset-dependent task (FR-061). No synthetic backfill on this
path (FR-063).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, UUIDPKMixin


class DatasetFreshnessRecord(Base, UUIDPKMixin):
    __tablename__ = "dataset_freshness_records"

    dataset_name: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    cadence: Mapped[str] = mapped_column(String(60), nullable=False)
    freshness_rule: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="unavailable")
    last_successful_update: Mapped[datetime | None]
    last_checksum_ok: Mapped[bool | None] = mapped_column(Boolean)
    retry_state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime]
