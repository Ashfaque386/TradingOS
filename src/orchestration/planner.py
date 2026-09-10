"""CEO planner: objective -> validated OrganizationalPlan (spec T025-T027, research R5,
FR-002..FR-008).

An LLM (``orchestration`` task type) does the judgement -- which departments, which agents, what
depends on what. Deterministic code then enforces the invariants (FR-007): the task/dependency
graph must be acyclic; every ``assigned_agent`` must exist and declare the task's capability;
every dependency must target an in-plan task; any safety-ordered stage present must appear in the
mandated order. On repeated failure the run is marked ``cannot_plan`` with a recorded decision
(FR-008) -- never a fabricated plan.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import structlog
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from src.agents.llm_router import complete
from src.agents.nodes.common import extract_json
from src.agents.prompt_registry import get_active_prompt
from src.models.orchestration import (
    OrganizationalDecision,
    OrganizationalPlan,
    OrganizationRun,
    Task,
    TaskDependency,
)
from src.orchestration import events
from src.orchestration.capability_registry import is_concurrency_safe, snapshot
from src.orchestration.enums import DecisionType, DependencyState, RunStatus, TaskStatus

logger = structlog.get_logger(__name__)

_MAX_PLAN_ATTEMPTS = 3
# The safety-critical chain -- when any of these capabilities appear in a plan they must appear
# in this relative order (FR-051, constitution IV). The planner may not reorder them.
_SAFETY_ORDER = (
    "code_validation",
    "compliance_check",
    "backtesting",
    "strategy_evaluation",
    "risk_assessment",
)


class _PlannedTask(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str
    objective: str
    capability: str
    assigned_agent: str
    priority: int = 5
    expected_output: str = "CeoSynthesis"
    depends_on: list[str] = Field(default_factory=list)


class _GeneratedPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    can_plan: bool = True
    reason: str | None = None
    objective_classification: str = "general"
    departments: list[str] = Field(default_factory=list)
    approval_required: bool = True
    tasks: list[_PlannedTask] = Field(default_factory=list)


class PlanValidationError(ValueError):
    """A generated plan failed a deterministic invariant (FR-007)."""


# Capabilities that mean "this plan will generate/implement a strategy" -- a plan like that MUST
# feed the research pipeline a `context_assembly` task fed by parallel news/sentiment/portfolio/
# market/freshness tasks (T053, FR-042/044). A pure analysis plan (no strategy output) is left
# exactly as the CEO produced it.
_STRATEGY_CAPS = frozenset({"strategy_generation", "strategy_research", "code_generation"})
# key, capability, assigned_agent, expected_output, scaffold-internal deps
_CONTEXT_SCAFFOLD: tuple[tuple[str, str, str, str, tuple[str, ...]], ...] = (
    ("ctx_news", "news_ingestion", "news_agent", "NewsDigest", ()),
    ("ctx_sentiment", "sentiment_analysis", "sentiment_agent", "SentimentReport", ("ctx_news",)),
    ("ctx_market", "market_analysis", "market_analyst", "MarketContext", ()),
    ("ctx_portfolio", "portfolio_read", "portfolio_manager_agent", "PortfolioRiskReport", ()),
    ("ctx_freshness", "data_freshness", "data_ingestion_agent", "AdHocAnalysis", ()),
    (
        "ctx_assembly",
        "context_assembly",
        "ceo_agent",
        "ResearchContext",
        ("ctx_news", "ctx_sentiment", "ctx_market", "ctx_portfolio", "ctx_freshness"),
    ),
)


def ensure_research_scaffold(plan: _GeneratedPlan) -> None:
    """Deterministically guarantee the news/sentiment/portfolio/market/freshness + context
    assembly tasks around any strategy-generating plan, and make every strategy task depend on
    the assembled ``ResearchContext`` (T053). Idempotent: reuses a task the CEO already planned
    for a given capability rather than duplicating it."""
    if not any(t.capability in _STRATEGY_CAPS for t in plan.tasks):
        return

    # capability -> the key that provides it (an existing CEO task wins over a scaffold key).
    key_for_cap: dict[str, str] = {t.capability: t.key for t in plan.tasks}
    cap_for_scaffold_key = {sk: cap for sk, cap, *_ in _CONTEXT_SCAFFOLD}
    for sk, capability, *_ in _CONTEXT_SCAFFOLD:
        key_for_cap.setdefault(capability, sk)

    for _sk, capability, agent, expected, dep_scaffold_keys in _CONTEXT_SCAFFOLD:
        if any(t.capability == capability for t in plan.tasks):
            continue
        plan.tasks.append(
            _PlannedTask(
                key=key_for_cap[capability],
                objective=f"Provide {capability.replace('_', ' ')} for this research objective.",
                capability=capability,
                assigned_agent=agent,
                priority=3,
                expected_output=expected,
                depends_on=[key_for_cap[cap_for_scaffold_key[dk]] for dk in dep_scaffold_keys],
            )
        )

    assembly_key = key_for_cap["context_assembly"]
    for t in plan.tasks:
        if t.capability in _STRATEGY_CAPS and assembly_key not in t.depends_on:
            t.depends_on.append(assembly_key)


def _validate(plan: _GeneratedPlan, known: dict[str, set[str]]) -> None:
    """``known`` maps agent name -> its declared capabilities. Raises PlanValidationError."""
    if not plan.tasks:
        raise PlanValidationError("plan has no tasks")
    keys = [t.key for t in plan.tasks]
    if len(keys) != len(set(keys)):
        raise PlanValidationError("duplicate task keys")
    keyset = set(keys)

    for t in plan.tasks:
        if t.assigned_agent not in known:
            raise PlanValidationError(f"task {t.key}: unknown agent '{t.assigned_agent}'")
        if t.capability not in known[t.assigned_agent]:
            raise PlanValidationError(
                f"task {t.key}: agent '{t.assigned_agent}' does not declare capability "
                f"'{t.capability}'"
            )
        for dep in t.depends_on:
            if dep not in keyset:
                raise PlanValidationError(
                    f"task {t.key}: dependency '{dep}' is not an in-plan task"
                )
            if dep == t.key:
                raise PlanValidationError(f"task {t.key}: self-dependency")

    _assert_acyclic(plan)
    _assert_safety_order(plan)


def _assert_acyclic(plan: _GeneratedPlan) -> None:
    graph = {t.key: set(t.depends_on) for t in plan.tasks}
    visited: set[str] = set()
    stack: set[str] = set()

    def visit(node: str) -> None:
        if node in stack:
            raise PlanValidationError(f"dependency cycle through task '{node}'")
        if node in visited:
            return
        stack.add(node)
        for nxt in graph.get(node, set()):
            visit(nxt)
        stack.discard(node)
        visited.add(node)

    for key in graph:
        visit(key)


def _assert_safety_order(plan: _GeneratedPlan) -> None:
    """If two safety-chain capabilities both appear, the earlier one must be a (transitive)
    dependency of the later one -- i.e. the plan may not let them run out of order or in
    parallel (FR-051)."""
    by_cap = {t.capability: t.key for t in plan.tasks if t.capability in _SAFETY_ORDER}
    present = [c for c in _SAFETY_ORDER if c in by_cap]
    if len(present) < 2:
        return
    reach: dict[str, set[str]] = {t.key: set() for t in plan.tasks}
    for t in plan.tasks:
        reach[t.key] = set(t.depends_on)
    changed = True
    while changed:
        changed = False
        for k, deps in reach.items():
            new = set(deps)
            for d in deps:
                new |= reach.get(d, set())
            if new != deps:
                reach[k] = new
                changed = True
    for earlier, later in zip(present, present[1:], strict=False):
        e_key, l_key = by_cap[earlier], by_cap[later]
        if e_key not in reach.get(l_key, set()):
            raise PlanValidationError(
                f"safety order violated: '{later}' must depend (transitively) on '{earlier}'"
            )


def _persist(session: Session, run: OrganizationRun, plan: _GeneratedPlan) -> OrganizationalPlan:
    now = datetime.now(UTC)
    plan_row = OrganizationalPlan(
        run_id=run.id,
        objective_classification=plan.objective_classification[:80],
        departments=plan.departments,
        constraints={},
        safety_requirements={
            "safety_chain": [c for c in _SAFETY_ORDER if any(t.capability == c for t in plan.tasks)]
        },
        approval_required=plan.approval_required,
        created_at=now,
    )
    session.add(plan_row)
    session.flush()
    run.plan_id = plan_row.id
    run.updated_at = now

    key_to_id: dict[str, uuid.UUID] = {}
    for t in plan.tasks:
        task_row = Task(
            plan_id=plan_row.id,
            run_id=run.id,
            tenant_id=run.tenant_id,
            objective=t.objective,
            assigned_agent=t.assigned_agent,
            assigned_by="ceo_agent",
            capability=t.capability,
            priority=t.priority,
            dependency_policy="all",
            required_inputs=[],
            received_inputs=[],
            expected_output=t.expected_output[:80],
            status=TaskStatus.PLANNED.value,
            is_concurrency_safe=is_concurrency_safe(t.capability),
            timeout_seconds=300,
            correlation_id=run.thread_id,
            created_at=now,
        )
        session.add(task_row)
        session.flush()
        key_to_id[t.key] = task_row.id

    for t in plan.tasks:
        for dep_key in t.depends_on:
            session.add(
                TaskDependency(
                    plan_id=plan_row.id,
                    dependent_task_id=key_to_id[t.key],
                    prerequisite_task_id=key_to_id[dep_key],
                    required_artefact_type=next(
                        (x.expected_output for x in plan.tasks if x.key == dep_key), "Artefact"
                    )[:80],
                    policy="hard",
                    state=DependencyState.UNSATISFIED.value,
                    created_at=now,
                )
            )
    session.flush()
    return plan_row


def generate_plan(session: Session, run: OrganizationRun) -> OrganizationalPlan | None:
    """Generate, validate, and persist the plan for ``run``. Returns the plan row, or ``None``
    (with the run set to ``cannot_plan`` + a recorded decision) if planning fails (FR-008)."""
    from src.memory.organization_memory import query_org_memory

    registry = snapshot(session)
    known = {a["name"]: set(a["capabilities"]) for a in registry if a["enabled"]}
    system_prompt = get_active_prompt("ceo_planner")
    memory = query_org_memory(run.objective, top_k=5)
    task_prompt_tmpl = get_active_prompt("ceo_planner_task")

    last_error = ""
    for attempt in range(1, _MAX_PLAN_ATTEMPTS + 1):
        user_prompt = task_prompt_tmpl.format(
            objective=run.objective,
            capability_snapshot=json.dumps(
                [
                    {
                        "name": a["name"],
                        "department": a["department"],
                        "capabilities": a["capabilities"],
                    }
                    for a in registry
                    if a["enabled"]
                ],
                indent=1,
            ),
            memory=json.dumps([m.get("text", "") for m in memory]) if memory else "[]",
        )
        if last_error:
            user_prompt += f"\n\nYour previous attempt was rejected: {last_error}\nFix it."
        try:
            response = complete(
                "orchestration",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            raw = extract_json(response.choices[0].message.content)
            plan = _GeneratedPlan.model_validate_json(raw)
        except Exception as exc:  # noqa: BLE001 -- any parse/LLM failure feeds back into the retry
            last_error = f"could not produce valid plan JSON ({exc})"
            logger.warning(
                "ceo_plan_attempt_failed", run_id=str(run.id), attempt=attempt, error=last_error
            )
            continue

        if not plan.can_plan:
            _record_cannot_plan(
                session, run, plan.reason or "the CEO judged the objective unservable"
            )
            return None
        try:
            _validate(plan, known)
            ensure_research_scaffold(plan)  # T053: deterministic context coverage
            _validate(plan, known)  # the injected scaffold must satisfy the same invariants
        except PlanValidationError as exc:
            last_error = str(exc)
            logger.warning(
                "ceo_plan_invalid", run_id=str(run.id), attempt=attempt, error=last_error
            )
            continue

        plan_row = _persist(session, run, plan)
        events.emit(
            session,
            run_id=run.id,
            event_type="organization.plan.created",
            subject_type="plan",
            subject_id=plan_row.id,
            payload={
                "task_count": len(plan.tasks),
                "departments": plan.departments,
                "dependency_count": sum(len(t.depends_on) for t in plan.tasks),
            },
            audited=True,
        )
        session.commit()
        return plan_row

    _record_cannot_plan(
        session, run, f"planner exhausted {_MAX_PLAN_ATTEMPTS} attempts: {last_error}"
    )
    return None


def _record_cannot_plan(session: Session, run: OrganizationRun, reason: str) -> None:
    now = datetime.now(UTC)
    run.status = RunStatus.CANNOT_PLAN.value
    run.ended_at = now
    run.updated_at = now
    session.add(
        OrganizationalDecision(
            run_id=run.id,
            decision_type=DecisionType.CANNOT_PLAN.value,
            summary="The organisation cannot serve this objective.",
            reason=reason,
            supporting_input_artefact_ids=[],
            supporting_agents=["ceo_agent"],
            created_at=now,
        )
    )
    events.emit(
        session,
        run_id=run.id,
        event_type="organization.run.cannot_plan",
        subject_type="run",
        subject_id=run.id,
        payload={"reason": reason},
        audited=True,
    )
    session.commit()
