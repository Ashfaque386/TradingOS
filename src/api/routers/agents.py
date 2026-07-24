"""Agent Console endpoints (Phase 4 Epic E4.3), backing Phase_7_Frontend_Architecture.md §2.1:

  - GET  /agents/graph                     -- static LangGraph topology (nodes/edges), real,
    introspected from the actual compiled graph (`build_graph().get_graph()`), not hand-copied.
  - POST /agents/research/trigger          -- starts a real graph run (real LLM calls through
    every node) in the background; returns immediately with a run id.
  - GET  /agents/runs                      -- recent graph-run history (DB-012 AgentRun).
  - GET  /agents/runs/{run_id}             -- one run's per-node child runs + their logs.
  - GET  /agents/prompts                   -- the prompt registry manifest (src/agents/
    prompt_registry.py), which agent maps to which prompt_id/active version.
  - GET  /agents/prompts/{slug}/versions/{version} -- a specific prompt version's content.
  - PUT  /agents/prompts/{slug}/active-version      -- hot-swap which version is active.

Before this router existed, nothing in the codebase ever invoked `build_graph()` outside tests,
and nothing ever called `publish_agent_log()` outside a test fixture -- the graph was real but
never run, and the `/stream/agents/logs` WS relay had no producer. `_execute_graph_run` below is
that producer: it streams the graph's real per-node execution (LangGraph's `stream_mode="updates"`
gives one real output dict per node as it actually completes -- no fabricated data), persists an
AgentRun/AgentLog row per node (DB-012/DB-013, previously defined but never written to), and
publishes each step to Redis so the Thought Stream panel has real content to show.

Auth/RBAC gap matches every other Phase 4 router: no JWT/auth module exists yet.
"""

import json
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.agents import prompt_registry
from src.agents.graph import build_graph
from src.agents.prompt_registry import PromptNotFoundError
from src.agents.state import TradingOSGraphState
from src.core.db import get_session
from src.engine.sandbox.strategy_factory import run_strategy_factory_pipeline
from src.memory.redis_client import get_redis_client, publish_agent_log
from src.models.account import Account
from src.models.agent import AgentLog, AgentRun
from src.models.strategy import Strategy, StrategyVersion

# No Risk Manager Agent exists yet to set a real per-strategy drawdown limit (Phase 4 scope,
# per Phase_14_Master_Development_Roadmap.md) -- mirrors kill_switch.py's
# DEFAULT_KILL_SWITCH_THRESHOLD (15%) rather than inventing an unrelated number.
_DEFAULT_MAX_DRAWDOWN_LIMIT = Decimal("15.00")

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])

GRAPH_ROOT_AGENT_NAME = "TradingOSGraph"


# --- Topology -----------------------------------------------------------------------------


class GraphNode(BaseModel):
    id: str


class GraphEdge(BaseModel):
    source: str
    target: str
    conditional: bool


class GraphTopologyResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


@router.get("/graph", response_model=GraphTopologyResponse)
def get_graph_topology() -> GraphTopologyResponse:
    representation = build_graph().get_graph()
    return GraphTopologyResponse(
        nodes=[GraphNode(id=node_id) for node_id in representation.nodes],
        edges=[
            GraphEdge(source=e.source, target=e.target, conditional=e.conditional)
            for e in representation.edges
        ],
    )


# --- Trigger a real run ---------------------------------------------------------------------


class TriggerResponse(BaseModel):
    run_id: uuid.UUID
    thread_id: str
    status: str


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _summarize_node_output(node_name: str, output: dict[str, Any]) -> str:
    """A short, honest summary of what a node actually returned -- built from the real
    Pydantic fields in `output`, never a canned string."""
    directive = output.get("research_directive")
    if directive is not None:
        return (
            f"Issued research directive: {directive.market_regime} regime, "
            f"sectors={directive.priority_sectors or 'none'}"
        )
    context = output.get("market_context")
    if context is not None:
        return f"Market context: confidence={context.confidence_score:.2f}, {context.macro_outlook}"
    strategy = output.get("strategy_logic")
    if strategy is not None:
        return f"Proposed strategy: {strategy.hypothesis} (confidence={strategy.confidence_score:.2f})"
    code = output.get("python_code")
    if code is not None:
        return f"Generated strategy code v{code.version_no} ({len(code.code)} chars)"
    validation = output.get("validation_result")
    if validation is not None:
        if validation.status == "Pass":
            return "Validation passed"
        return f"Validation failed ({validation.severity}): {validation.feedback}"
    if node_name == "await_backtesting":
        return "Awaiting Phase 3 backtesting engine (not yet wired into the live graph)"
    return f"{node_name} completed with no new state fields"


@dataclass
class _StrategyTracking:
    """Local-to-one-run state threaded through `_execute_graph_run`'s node loop -- not global,
    since each concurrent run builds its own Strategy/StrategyVersion lineage."""

    strategy_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None
    account_lookup_done: bool = False


def _persist_strategy_progress(
    session: Session, *, node_name: str, output: dict[str, Any], tracking: _StrategyTracking
) -> None:
    """Real persistence for DB-005/DB-006 (Strategy/StrategyVersion, src/models/strategy.py):
    before this, nothing in the codebase ever wrote a row to either table (confirmed by
    exhaustive grep before building this) -- the Strategy Deployment Kanban
    (Phase_7_Frontend_Architecture.md §2.3) had nothing to show. Mirrors the AgentRun/AgentLog
    persistence just above: hook real DB writes onto the graph's real per-node output, no
    fabricated intermediate state."""
    if node_name == "strategy_generator" and "strategy_logic" in output:
        if not tracking.account_lookup_done:
            tracking.account_id = session.scalars(select(Account.id)).first()
            tracking.account_lookup_done = True
        if tracking.account_id is None:
            return  # no Account seeded yet -- can't satisfy Strategy.account_id's NOT NULL FK

        logic = output["strategy_logic"]
        strategy = Strategy(
            account_id=tracking.account_id,
            name=logic.hypothesis[:150],
            hypothesis=logic.hypothesis,
            asset_class=logic.asset_class,
            style=logic.style,
            status="Ideation",
            max_drawdown_limit=_DEFAULT_MAX_DRAWDOWN_LIMIT,
            universe=logic.universe or None,
        )
        session.add(strategy)
        session.flush()
        tracking.strategy_id = strategy.id
        return

    if tracking.strategy_id is None:
        return  # strategy_generator hasn't run yet this thread (or its account lookup failed)

    if node_name == "python_code_generator" and "python_code" in output:
        code = output["python_code"]
        version = StrategyVersion(
            strategy_id=tracking.strategy_id,
            version_no=code.version_no,
            python_code=code.code,
            validation_status="Pending",
        )
        session.add(version)
        session.flush()
        strategy = session.get(Strategy, tracking.strategy_id)
        if strategy is not None:
            strategy.current_version_id = version.id
            strategy.status = "Coding"
        return

    if node_name == "python_validator" and "validation_result" in output:
        strategy = session.get(Strategy, tracking.strategy_id)
        if strategy is None or strategy.current_version_id is None:
            return
        if output["validation_result"].status != "Pass":
            return  # a retry produces a new StrategyVersion via the branch above; nothing to do here
        version = session.get(StrategyVersion, strategy.current_version_id)
        if version is None:
            return
        # Real sandbox re-validation + .py persistence via the tested Phase 3 pipeline (writes
        # {data_lake_root.parent}/strategies/{version_id}.py and updates
        # StrategyVersion.validation_status itself) -- reused rather than re-implemented here.
        run_strategy_factory_pipeline(version.python_code, strategy_version_id=str(version.id))
        strategy.status = "Backtesting"


def _execute_graph_run(*, thread_id: str, root_run_id: uuid.UUID) -> None:
    """Runs in a FastAPI BackgroundTasks worker thread (dispatched after the trigger endpoint
    already returned). Synchronous end-to-end because every graph node (src/agents/nodes/*.py)
    and `graph.stream()` itself are synchronous."""
    redis_client = get_redis_client()
    graph = build_graph()
    state = TradingOSGraphState(thread_id=thread_id)
    checkpoint_wall = datetime.now(UTC)
    tracking = _StrategyTracking()

    try:
        for step in graph.stream(state):
            for node_name, output in step.items():
                now_wall = datetime.now(UTC)
                summary = _summarize_node_output(node_name, output)

                with get_session() as session:
                    child = AgentRun(
                        graph_thread_id=thread_id,
                        agent_name=node_name,
                        parent_run_id=root_run_id,
                        output_state={k: _jsonable(v) for k, v in output.items()},
                        status="Completed",
                        started_at=checkpoint_wall,
                        ended_at=now_wall,
                    )
                    session.add(child)
                    session.flush()
                    session.add(
                        AgentLog(
                            agent_run_id=child.id,
                            log_level="INFO",
                            message=summary,
                            created_at=now_wall,
                        )
                    )
                    _persist_strategy_progress(
                        session, node_name=node_name, output=output, tracking=tracking
                    )
                    session.commit()

                publish_agent_log(
                    redis_client,
                    json.dumps(
                        {
                            "agent_id": node_name,
                            "node": node_name,
                            "message": summary,
                            "ts": now_wall.isoformat(),
                        }
                    ),
                )
                checkpoint_wall = now_wall

        with get_session() as session:
            root = session.get(AgentRun, root_run_id)
            if root is not None:
                root.status = "Completed"
                root.ended_at = datetime.now(UTC)
                session.commit()
    except Exception as exc:  # noqa: BLE001 -- must always close out the run row, even on failure
        error_ts = datetime.now(UTC)
        with get_session() as session:
            root = session.get(AgentRun, root_run_id)
            if root is not None:
                root.status = "Failed"
                root.ended_at = error_ts
                session.add(
                    AgentLog(
                        agent_run_id=root_run_id,
                        log_level="ERROR",
                        message=str(exc),
                        created_at=error_ts,
                    )
                )
                session.commit()
        publish_agent_log(
            redis_client,
            json.dumps(
                {
                    "agent_id": GRAPH_ROOT_AGENT_NAME,
                    "node": GRAPH_ROOT_AGENT_NAME,
                    "message": f"Run failed: {exc}",
                    "ts": error_ts.isoformat(),
                }
            ),
        )
    finally:
        redis_client.close()


@router.post("/research/trigger", response_model=TriggerResponse, status_code=202)
def trigger_research() -> TriggerResponse:
    """Starts one real end-to-end graph run (CEO -> Market Analyst -> Strategy Generator ->
    Code Gen -> Validator loop). Every node makes a real LLM call through
    src/agents/llm_router.py against whichever provider is configured -- this is not a dry run.

    Dispatched via a detached `threading.Thread`, not FastAPI's `BackgroundTasks`: Starlette
    awaits every registered BackgroundTask during graceful shutdown, and a single node here can
    take up to the LLM client's timeout (Ollama's fallback path alone can run ~600s). With
    `--reload` that meant editing any file blocked the dev server from restarting until the
    in-flight LLM call finished or timed out -- confirmed by hand, it once stalled a reload for
    ~10 minutes. A daemon thread isn't tracked by Starlette's shutdown sequence, so `--reload`
    (and `docker compose restart`) return immediately; the run keeps executing and still writes
    its AgentRun/AgentLog rows for whoever's watching, it just isn't graceful if the process
    exits mid-run -- acceptable for this dev-only trigger endpoint."""
    thread_id = str(uuid.uuid4())
    started_at = datetime.now(UTC)

    with get_session() as session:
        root = AgentRun(
            graph_thread_id=thread_id,
            agent_name=GRAPH_ROOT_AGENT_NAME,
            status="Running",
            started_at=started_at,
        )
        session.add(root)
        session.commit()
        run_id = root.id

    threading.Thread(
        target=_execute_graph_run,
        kwargs={"thread_id": thread_id, "root_run_id": run_id},
        daemon=True,
    ).start()
    return TriggerResponse(run_id=run_id, thread_id=thread_id, status="Running")


# --- Run history ------------------------------------------------------------------------------


class AgentLogEntry(BaseModel):
    node: str
    log_level: str
    message: str
    created_at: datetime


class AgentRunSummary(BaseModel):
    run_id: uuid.UUID
    thread_id: str
    agent_name: str
    status: str
    started_at: datetime
    ended_at: datetime | None


class AgentRunDetail(AgentRunSummary):
    nodes: list[AgentRunSummary]
    logs: list[AgentLogEntry]


def _to_summary(run: AgentRun) -> AgentRunSummary:
    return AgentRunSummary(
        run_id=run.id,
        thread_id=run.graph_thread_id,
        agent_name=run.agent_name,
        status=run.status,
        started_at=run.started_at,
        ended_at=run.ended_at,
    )


@router.get("/runs", response_model=list[AgentRunSummary])
def list_runs() -> list[AgentRunSummary]:
    with get_session() as session:
        roots = session.scalars(
            select(AgentRun)
            .where(AgentRun.parent_run_id.is_(None))
            .order_by(AgentRun.started_at.desc())
            .limit(20)
        )
        return [_to_summary(r) for r in roots]


@router.get("/runs/{run_id}", response_model=AgentRunDetail)
def get_run(run_id: uuid.UUID) -> AgentRunDetail:
    """Logs are attached to each per-node child AgentRun (see `_execute_graph_run`), not the
    root -- so the Thought Stream needs logs from the root run itself plus every child node,
    merged in chronological order, not just `AgentLog.agent_run_id == run_id`."""
    with get_session() as session:
        root = session.get(AgentRun, run_id)
        if root is None:
            raise HTTPException(status_code=404, detail="Run not found")
        children = list(
            session.scalars(
                select(AgentRun)
                .where(AgentRun.parent_run_id == run_id)
                .order_by(AgentRun.started_at)
            )
        )
        run_ids_by_agent = {run_id: root.agent_name, **{c.id: c.agent_name for c in children}}
        logs = session.scalars(
            select(AgentLog)
            .where(AgentLog.agent_run_id.in_(run_ids_by_agent.keys()))
            .order_by(AgentLog.created_at)
        )
        return AgentRunDetail(
            **_to_summary(root).model_dump(),
            nodes=[_to_summary(c) for c in children],
            logs=[
                AgentLogEntry(
                    node=run_ids_by_agent[log.agent_run_id],
                    log_level=log.log_level,
                    message=log.message,
                    created_at=log.created_at,
                )
                for log in logs
            ],
        )


# --- Prompt registry (Prompt Management Interface) -------------------------------------------


class PromptSummary(BaseModel):
    agent_slug: str
    prompt_id: str
    active_version: int
    available_versions: list[int]


class PromptVersionContent(BaseModel):
    agent_slug: str
    version: int
    content: str


class SetActiveVersionRequest(BaseModel):
    version: int


@router.get("/prompts", response_model=list[PromptSummary])
def list_prompts() -> list[PromptSummary]:
    manifest = prompt_registry.list_agents()
    return [
        PromptSummary(
            agent_slug=slug,
            prompt_id=entry["prompt_id"],
            active_version=entry["active_version"],
            available_versions=prompt_registry.list_versions(slug),
        )
        for slug, entry in manifest.items()
    ]


@router.get("/prompts/{slug}/versions/{version}", response_model=PromptVersionContent)
def get_prompt_version(slug: str, version: int) -> PromptVersionContent:
    try:
        content = prompt_registry.get_prompt_version(slug, version)
    except PromptNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PromptVersionContent(agent_slug=slug, version=version, content=content)


@router.put("/prompts/{slug}/active-version", response_model=PromptSummary)
def set_active_version(slug: str, body: SetActiveVersionRequest) -> PromptSummary:
    try:
        prompt_registry.set_active_version(slug, body.version)
    except PromptNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    manifest = prompt_registry.list_agents()
    entry = manifest[slug]
    return PromptSummary(
        agent_slug=slug,
        prompt_id=entry["prompt_id"],
        active_version=entry["active_version"],
        available_versions=prompt_registry.list_versions(slug),
    )
