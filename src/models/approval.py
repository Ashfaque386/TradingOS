"""ApprovalRequest -- the real pre-transition human approval gate (spec T007, data-model.md §7,
FR-052..057, clarify Q1). Replaces the audit's post-hoc no-op `approve_run` (BUG-B).

A deployment recommendation puts the strategy in status ``PendingPaperApproval`` and creates a
``pending`` row here. Only ``SystemAdministrator`` / ``PortfolioManager`` may approve (→
``PaperTrading``) or reject (→ ``Deprecated``, ``reason`` required). No timeout ever
auto-resolves it (FR-057).
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, UUIDPKMixin


class ApprovalRequest(Base, UUIDPKMixin):
    __tablename__ = "approval_requests"

    # Nullable: a deployment recommendation from the legacy research graph (no OrganizationRun)
    # also opens a real gate; org-led runs set this so `run_manager` can hold the run `waiting`.
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization_runs.id")
    )
    strategy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategies.id"), nullable=False
    )
    strategy_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategy_versions.id")
    )
    recommendation_artefact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("result_artefacts.id")
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    decided_by: Mapped[str | None] = mapped_column(String(255))
    decided_at: Mapped[datetime | None]
    # Required (service-layer enforced, FR-053) when status == "rejected".
    reason: Mapped[str | None] = mapped_column(Text)
    audit_reference: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("audit_log.id"))
    created_at: Mapped[datetime]
