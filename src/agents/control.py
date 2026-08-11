"""Per-agent control state (REL-019 E19.2, ADR 11).

ADR 11 (Phase_1_Architecture_Decision_Record.md) decided per-agent disable means a halt-on-entry
circuit breaker for the LangGraph pipeline nodes (11 originally, 12 since REL-025's `memory_ingest`
node, 13 since REL-030's `options_strategy_agent` -- the run stops before a disabled node's real
logic executes -- src/agents/graph.py wraps every `add_node()` registration with
`require_enabled()` below) and a real skip-this-call check for agents invoked outside the graph
(src/agents/scheduler.py checks `is_agent_enabled()` before dispatching News/Sentiment/Memory/
Data Ingestion). This module is the one shared primitive both call.

`is_agent_enabled()`/`require_enabled()` read the real `agent_control_state` table -- no row for
a given `agent_name` means enabled (fail-open default; only an explicit disable ever gets a row).
`set_agent_enabled()` writes it, refusing to disable `AUDIT_AGENT_NAME`: Business Rule 5
(immutable AI/trade audit trail) makes turning off the audit trail a compliance violation, not an
operational convenience.

UPDATE 2026-08-05 (REL-025): a 12th graph_node entry, `memory_ingest`, was added -- a real second
call site for AGT-009 (Memory Agent), distinct from the `memory_agent` scheduled weekend-archival
entry below. Both write to the same `trading_strategies` Qdrant collection but are operationally
independent (one is a per-FAIL real-time graph node, the other a batch job), so they get separate
toggleable control-state rows rather than sharing one lever.

UPDATE 2026-08-07 (REL-030): AGT-015 (Options Strategy Agent) moves from `registry_only`/
`enforced=False` to a real 13th `graph_node`/`enforced=True` entry -- `src/agents/graph.py` now
has a real call site (between `strategy_generator` and `python_code_generator`), the same
registry_only -> graph_node upgrade REL-025 gave `memory_ingest`.

`KNOWN_AGENTS` is the full real-agent registry backing the E19.3 console UI: every agent the
ERDTM AI Agent Traceability sheet currently marks REAL and still-shipped (AGT-017/018/019 -- the
ML/RL agents -- are excluded; their code was removed from the running system 2026-07-30, see
Release Traceability REL-008/009). `enforced=True` means a real call site checks this agent's
state today; `enforced=False` means the control row is real and toggleable (the API/UI never
lies about what state is stored) but no call site enforces it yet -- an honest scope boundary for
agents invoked from routers/skill dispatch this pass didn't wire (Execution, Portfolio Manager,
Notification, Skill Registry Manager, Scheduler itself, CEO Chat)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.agent import AgentControlState

AUDIT_AGENT_NAME = "audit_agent"

AgentKind = Literal["graph_node", "scheduled", "registry_only"]


@dataclass(frozen=True)
class AgentDescriptor:
    name: str
    agent_id: str
    display_name: str
    kind: AgentKind
    enforced: bool


KNOWN_AGENTS: tuple[AgentDescriptor, ...] = (
    # 11 LangGraph pipeline nodes -- halt-on-entry, wrapped centrally in src/agents/graph.py.
    # `name` matches the exact graph node key already used as AgentRun.agent_name everywhere
    # else in this codebase, not a new naming scheme.
    AgentDescriptor("ceo_agent", "AGT-001", "CEO Agent (Master Orchestrator)", "graph_node", True),
    AgentDescriptor("market_analyst", "AGT-002", "Market Analyst Agent", "graph_node", True),
    AgentDescriptor(
        "strategy_generator", "AGT-003", "Strategy Generator Agent", "graph_node", True
    ),
    AgentDescriptor(
        "python_code_generator", "AGT-004", "Python Code Generator Agent", "graph_node", True
    ),
    AgentDescriptor("compliance", "AGT-020", "Compliance Agent", "graph_node", True),
    AgentDescriptor("python_validator", "AGT-005", "Python Validator Agent", "graph_node", True),
    AgentDescriptor("backtesting", "AGT-006", "Backtesting Agent", "graph_node", True),
    AgentDescriptor("evaluator", "AGT-011", "Evaluator Agent", "graph_node", True),
    AgentDescriptor(
        "memory_ingest", "AGT-009", "Memory Agent (Failure Ingestion)", "graph_node", True
    ),
    AgentDescriptor(
        "optimization", "AGT-007", "Optimization Agent (Walk-Forward)", "graph_node", True
    ),
    AgentDescriptor("risk_manager", "AGT-008", "Risk Manager Agent (AI Layer)", "graph_node", True),
    AgentDescriptor("deployment", "AGT-012", "Deployment Agent", "graph_node", True),
    # REL-030: real 13th graph node, between strategy_generator and python_code_generator --
    # AGT-015 moves from registry_only/False to a real halt-on-entry graph_node/True, same
    # upgrade REL-025 gave memory_ingest.
    AgentDescriptor(
        "options_strategy_agent", "AGT-015", "Options Strategy Agent", "graph_node", True
    ),
    # Non-graph agents dispatched from a single src/agents/scheduler.py call site each --
    # real skip-this-call enforcement, not just a stored toggle.
    AgentDescriptor("memory_agent", "AGT-009", "Memory Agent", "scheduled", True),
    AgentDescriptor("news_agent", "AGT-013", "News Agent", "scheduled", True),
    AgentDescriptor("sentiment_agent", "AGT-014", "Sentiment Agent", "scheduled", True),
    AgentDescriptor("data_ingestion_agent", "AGT-024", "Data Ingestion Agent", "scheduled", True),
    # REL-034: real skip-this-call enforcement in src/engine/paper_trading/daily_signal_job.py,
    # same pattern as the other scheduled entries above -- an operator can halt the paper
    # account's autonomous daily trading without redeploying.
    AgentDescriptor("paper_trading_engine", "AGT-027", "Paper Trading Engine", "scheduled", True),
    # Non-graph agents invoked via API/skill dispatch -- real, toggleable state; call-site
    # enforcement not yet wired this pass (see module docstring).
    AgentDescriptor("execution_agent", "AGT-010", "Execution Agent (Live)", "registry_only", False),
    AgentDescriptor(
        "portfolio_manager_agent", "AGT-016", "Portfolio Manager Agent", "registry_only", False
    ),
    AgentDescriptor(AUDIT_AGENT_NAME, "AGT-021", "Audit Agent", "registry_only", False),
    AgentDescriptor(
        "notification_agent", "AGT-022", "Notification / Omni-Channel Agent", "registry_only", False
    ),
    AgentDescriptor(
        "skill_registry_manager_agent",
        "AGT-023",
        "Skill Registry Manager Agent",
        "registry_only",
        False,
    ),
    AgentDescriptor("scheduler_agent", "AGT-025", "Scheduler Agent", "registry_only", False),
    AgentDescriptor(
        "ceo_agent_chat", "AGT-026", "CEO Agent (Chat Interface)", "registry_only", False
    ),
)

_KNOWN_AGENT_NAMES = {a.name for a in KNOWN_AGENTS}


class UnknownAgentError(ValueError):
    pass


class AgentHaltedError(Exception):
    """Raised by the halt-on-entry graph wrapper / scheduler skip-check when a disabled agent's
    real logic would otherwise have run."""

    def __init__(self, agent_name: str, reason: str | None) -> None:
        self.agent_name = agent_name
        self.reason = reason
        detail = f": {reason}" if reason else ""
        super().__init__(f"Agent '{agent_name}' is administratively disabled{detail}")


def _get_row(session: Session, agent_name: str) -> AgentControlState | None:
    return session.scalars(
        select(AgentControlState).where(AgentControlState.agent_name == agent_name)
    ).first()


def is_agent_enabled(session: Session, agent_name: str) -> bool:
    row = _get_row(session, agent_name)
    return row is None or row.enabled


def require_enabled(session: Session, agent_name: str) -> None:
    row = _get_row(session, agent_name)
    if row is not None and not row.enabled:
        raise AgentHaltedError(agent_name, row.reason)


def set_agent_enabled(
    session: Session,
    *,
    agent_name: str,
    enabled: bool,
    reason: str | None,
    updated_by_user_id: uuid.UUID,
) -> AgentControlState:
    if agent_name not in _KNOWN_AGENT_NAMES:
        raise UnknownAgentError(agent_name)
    if agent_name == AUDIT_AGENT_NAME and not enabled:
        raise ValueError(
            "The Audit Agent cannot be disabled -- Business Rule 5 requires an immutable "
            "AI/trade audit trail at all times."
        )
    row = _get_row(session, agent_name)
    now = datetime.now(UTC)
    if row is None:
        row = AgentControlState(
            agent_name=agent_name,
            enabled=enabled,
            reason=reason,
            updated_by_user_id=updated_by_user_id,
            updated_at=now,
        )
        session.add(row)
    else:
        row.enabled = enabled
        row.reason = reason
        row.updated_by_user_id = updated_by_user_id
        row.updated_at = now
    session.flush()
    return row
