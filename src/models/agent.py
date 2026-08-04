import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, UUIDPKMixin


class AgentRun(Base, UUIDPKMixin):
    """DB-012. LangGraph node execution ledger. Satisfies NFR-05 (100% LLM call tracing)."""

    __tablename__ = "agent_runs"

    graph_thread_id: Mapped[str] = mapped_column(String(100), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(50), nullable=False)
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id")
    )
    input_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    output_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="Running")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime]
    ended_at: Mapped[datetime | None]
    langsmith_trace_url: Mapped[str | None] = mapped_column(String(255))
    # REL-010 E10.8d: Orchestrator HITL (POST /agents/runs/{id}/approve|reject|retry).
    human_decision: Mapped[str | None] = mapped_column(String(20))
    retried_from_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id")
    )


class AgentControlState(Base, UUIDPKMixin):
    """DB-034. REL-019 E19.2 (ADR 11) -- per-agent enable/disable control state, the durable
    admin-configuration primitive ADR 11 (Phase_1_Architecture_Decision_Record.md) calls for.
    Deliberately separate from AgentRun (a per-run-instance ledger with NOT NULL run-lifecycle
    columns) and from TradingOSGraphState (per-run state, `extra="forbid"`) -- neither fits an
    abstract "is this agent currently enabled" concept. No row for a given `agent_name` means
    enabled (fail-open default, src/agents/control.py::is_agent_enabled) -- only an explicit
    disable ever gets a row."""

    __tablename__ = "agent_control_state"

    agent_name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    reason: Mapped[str | None] = mapped_column(Text)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    updated_at: Mapped[datetime]


class AgentLog(Base, UUIDPKMixin):
    """DB-013. Agent reasoning/tool-call logs. Rolling 90-day hot retention (Phase_11 §5.2)."""

    __tablename__ = "agent_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)  # type: ignore[assignment]
    agent_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id"), nullable=False
    )
    log_level: Mapped[str] = mapped_column(String(10), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    tool_call: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    token_usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime]
