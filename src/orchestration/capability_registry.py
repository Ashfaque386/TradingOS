"""Agent capability registry (spec T019/T020, research R6, FR-006/FR-016/FR-086/FR-110).

The CEO planner selects agents *by capability*, not by hard-coded agent id. This module is the
one place that view is assembled: it merges the code-authoritative ``KNOWN_AGENTS`` roster
(``src/agents/control.py``) with the organisation metadata below (department, capabilities,
whether the agent makes a real LLM call, its concurrency limit) and the live enabled/health
state, and serves it as a snapshot to the planner and the console directory.

``CONCURRENCY_SAFE_CAPABILITIES`` (spec T023, A-8, research R2) is the reviewed allowlist of
capabilities the task engine may run in parallel -- everything else serialises.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.agents.control import KNOWN_AGENTS, is_agent_enabled

# Departments (FR-086).
EXECUTIVE = "Executive"
MARKET_INTELLIGENCE = "Market Intelligence"
RESEARCH = "Research"
QUANT = "Quant"
RISK_GOVERNANCE = "Risk & Governance"
PORTFOLIO = "Portfolio"
OPERATIONS = "Operations"


@dataclass(frozen=True)
class _Meta:
    department: str
    capabilities: tuple[str, ...]
    is_llm_backed: bool
    concurrency_limit: int = 1


# Authoritative per-agent organisation metadata (T019). Keyed by the agent `name` in KNOWN_AGENTS.
AGENT_META: dict[str, _Meta] = {
    "ceo_agent": _Meta(
        EXECUTIVE, ("orchestrate", "synthesize", "decide", "context_assembly"), True
    ),
    "ceo_agent_chat": _Meta(EXECUTIVE, ("converse",), True),
    "market_analyst": _Meta(MARKET_INTELLIGENCE, ("market_analysis",), True),
    "news_agent": _Meta(MARKET_INTELLIGENCE, ("news_ingestion",), False),
    "sentiment_agent": _Meta(MARKET_INTELLIGENCE, ("sentiment_analysis",), True),
    "strategy_generator": _Meta(RESEARCH, ("strategy_generation",), True),
    "options_strategy_agent": _Meta(RESEARCH, ("options_strategy_generation",), True),
    "python_code_generator": _Meta(QUANT, ("code_generation",), True),
    "python_validator": _Meta(QUANT, ("code_validation",), False),
    "backtesting": _Meta(QUANT, ("backtesting", "strategy_research"), False),
    "optimization": _Meta(QUANT, ("optimization",), False),
    "evaluator": _Meta(QUANT, ("strategy_evaluation",), False),
    "risk_manager": _Meta(RISK_GOVERNANCE, ("risk_assessment",), True),
    "compliance": _Meta(RISK_GOVERNANCE, ("compliance_check",), False),
    "audit_agent": _Meta(RISK_GOVERNANCE, ("audit",), False),
    "deployment": _Meta(RISK_GOVERNANCE, ("deployment_recommendation",), True),
    "portfolio_manager_agent": _Meta(PORTFOLIO, ("capital_allocation", "portfolio_read"), True),
    "memory_agent": _Meta(OPERATIONS, ("memory_maintenance",), True),
    "memory_ingest": _Meta(OPERATIONS, ("memory_ingestion",), False),
    "data_ingestion_agent": _Meta(OPERATIONS, ("data_ingestion", "data_freshness"), False),
    "scheduler_agent": _Meta(OPERATIONS, ("scheduling",), False),
    "notification_agent": _Meta(OPERATIONS, ("notification",), False),
    "skill_registry_manager_agent": _Meta(OPERATIONS, ("skill_administration",), False),
    "execution_agent": _Meta(OPERATIONS, ("order_execution",), False),
    "paper_trading_engine": _Meta(OPERATIONS, ("paper_trading",), False),
}

# spec T023 / A-8 / research R2: capabilities the task engine may run concurrently. Anything
# touching the kill-switch singleton, the shared sandbox pool, a broker write, or an
# Alembic-guarded table is deliberately excluded.
CONCURRENCY_SAFE_CAPABILITIES: frozenset[str] = frozenset(
    {
        "market_analysis",
        "news_ingestion",
        "sentiment_analysis",
        "portfolio_read",
        "data_freshness",
        "memory_ingestion",
        "memory_maintenance",
        "synthesize",
        "context_assembly",
    }
)


class AgentSnapshotRow(TypedDict):
    name: str
    agent_id: str
    display_name: str
    kind: str
    department: str
    capabilities: list[str]
    is_llm_backed: bool
    concurrency_limit: int
    enabled: bool
    health: str


def _latest_run_status_by_agent(session: Session) -> dict[str, str]:
    """Most recent ``AgentRun.status`` per ``agent_name`` in one ``DISTINCT ON`` query."""
    from src.models.agent import AgentRun

    rows = session.execute(
        select(AgentRun.agent_name, AgentRun.status)
        .distinct(AgentRun.agent_name)
        .order_by(AgentRun.agent_name, AgentRun.started_at.desc())
    ).all()
    return {name: status for name, status in rows}


def derive_health(*, enabled: bool, last_run_status: str | None) -> str:
    """A real, honest per-agent health signal (US5, FR-016) -- never fabricated."""
    if not enabled:
        return "disabled"
    if last_run_status == "Failed":
        return "degraded"
    if last_run_status == "Running":
        return "running"
    return "idle"


def snapshot(session: Session) -> list[AgentSnapshotRow]:
    """The planner's view of the organisation (FR-006). Real enabled state from
    ``agent_control_state`` and a real ``health`` derived from each agent's most recent
    ``AgentRun`` (US5)."""
    last_status = _latest_run_status_by_agent(session)
    out: list[AgentSnapshotRow] = []
    for descriptor in KNOWN_AGENTS:
        meta = AGENT_META.get(descriptor.name)
        enabled = is_agent_enabled(session, descriptor.name)
        out.append(
            AgentSnapshotRow(
                name=descriptor.name,
                agent_id=descriptor.agent_id,
                display_name=descriptor.display_name,
                kind=descriptor.kind,
                department=meta.department if meta else OPERATIONS,
                capabilities=list(meta.capabilities) if meta else [],
                is_llm_backed=meta.is_llm_backed if meta else True,
                concurrency_limit=meta.concurrency_limit if meta else 1,
                enabled=enabled,
                health=derive_health(
                    enabled=enabled, last_run_status=last_status.get(descriptor.name)
                ),
            )
        )
    return out


def find_by_capability(session: Session, capability: str) -> list[str]:
    """Names of enabled agents that declare ``capability`` (FR-006)."""
    return [
        row["name"]
        for row in snapshot(session)
        if capability in row["capabilities"] and row["enabled"]
    ]


def is_concurrency_safe(capability: str) -> bool:
    return capability in CONCURRENCY_SAFE_CAPABILITIES
