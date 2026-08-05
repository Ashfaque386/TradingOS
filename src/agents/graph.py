"""LangGraph state machine (Phase 2 Epic E2.1 + REL-005 Epic E5), matching the state diagram in
Phase_3_Low_Level_Design.md §2:

    Research -> Strategy Generator -> Code Gen/Validator loop -> Backtest/Evaluator loop
    -> Optimization -> Risk -> Deployment

REL-005 closes the loop that used to terminate at `await_backtesting`, a Phase 2 placeholder --
Backtesting, Evaluator, Optimization, Risk Manager, and Deployment now all run for real. The
Backtest_Loop's escalation rule (5 consecutive strategy rejections -> escalate to CEO) is enforced
below by `route_after_memory_ingest` (moved there by REL-025, see below -- was originally
`route_after_evaluation`'s own FAIL branch): `strategy_generator_node` increments
`strategy_rejection_count` on every FAIL verdict it receives, so by the time this routing function
runs after a FAIL, the count already reflects the prior loop iteration's rejection -- no separate
increment happens here. `ceo_agent_node` resets the counter to 0 on every entry (see its own
docstring), so an escalated re-entry gets a fresh 5-strikes budget rather than immediately
re-escalating.

REL-025: every FAIL verdict now passes through a real `memory_ingest` node before the graph
decides retry-vs-escalate, so a rejected strategy is never silently dropped without a Qdrant
record (`route_after_evaluation`'s FAIL branch used to go straight to `strategy_generator`/
`ceo_agent`; it now always goes to `memory_ingest` first, which then routes onward via
`route_after_memory_ingest`).
"""

from collections.abc import Callable
from typing import Any

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.agents.control import require_enabled
from src.agents.nodes.backtesting import backtesting_node
from src.agents.nodes.ceo import ceo_agent_node
from src.agents.nodes.compliance import compliance_node
from src.agents.nodes.deployment import deployment_node
from src.agents.nodes.evaluator import evaluator_node
from src.agents.nodes.market_analyst import market_analyst_node
from src.agents.nodes.memory_ingest import memory_ingest_node
from src.agents.nodes.optimization import optimization_node
from src.agents.nodes.python_code_generator import python_code_generator_node
from src.agents.nodes.python_validator import python_validator_node
from src.agents.nodes.risk_manager import risk_manager_node
from src.agents.nodes.strategy_generator import strategy_generator_node
from src.agents.state import TradingOSGraphState
from src.core.db import get_session

MAX_CODE_VALIDATION_RETRIES = 3
MAX_REJECTIONS_BEFORE_ESCALATION = 5

NodeFn = Callable[[TradingOSGraphState], dict[str, Any]]


def _halt_on_entry(node_name: str, node_fn: NodeFn) -> NodeFn:
    """ADR 11's halt-on-entry circuit breaker: checked before `node_fn`'s real logic runs, not
    after. A disabled node raises `AgentHaltedError` here -- the run genuinely never executes
    that node's logic, rather than being skipped-past with fabricated state (see ADR 11's
    "Alternatives Considered" for why that was rejected, e.g. for the `compliance` node, a
    hardcoded safety veto that must never be silently bypassed)."""

    def wrapper(state: TradingOSGraphState) -> dict[str, Any]:
        with get_session() as session:
            require_enabled(session, node_name)
        return node_fn(state)

    return wrapper


def route_after_validation(state: TradingOSGraphState) -> str:
    if state.validation_result is None:
        raise ValueError("route_after_validation called before python_validator_node ran")
    if state.validation_result.status == "Pass":
        return "backtesting"
    if state.code_validation_retry_count >= MAX_CODE_VALIDATION_RETRIES:
        return "END"  # "fail gracefully" per Phase_4 §5 / Phase 2 Epic 1 acceptance criteria
    return "python_code_generator"


def route_after_compliance(state: TradingOSGraphState) -> str:
    if state.compliance_verdict is None:
        raise ValueError("route_after_compliance called before compliance_node ran")
    if state.compliance_verdict.verdict == "Block":
        return "END"
    return "python_validator"


def route_after_evaluation(state: TradingOSGraphState) -> str:
    if state.evaluation_verdict is None:
        raise ValueError("route_after_evaluation called before evaluator_node ran")
    if state.evaluation_verdict.verdict == "PASS":
        return "optimization"
    # REL-025: every FAIL ingests into memory first -- route_after_memory_ingest (below) makes
    # the retry-vs-escalate decision that used to happen directly here.
    return "memory_ingest"


def route_after_memory_ingest(state: TradingOSGraphState) -> str:
    if state.strategy_rejection_count >= MAX_REJECTIONS_BEFORE_ESCALATION:
        return "ceo_agent"  # escalate: loosen constraints per Phase_4 §11/§3
    return "strategy_generator"


def build_graph() -> CompiledStateGraph:  # type: ignore[type-arg]
    graph = StateGraph(TradingOSGraphState)

    # mypy --strict can resolve add_node's generic NodeInputT overloads against a directly-named
    # node function (it reads the function's own declared signature), but not against the
    # `_halt_on_entry` closure below -- a known mypy limitation with overloaded+generic Protocol
    # matching on wrapped callables, not a real type-safety gap: `wrapper` is structurally a
    # valid `_Node[TradingOSGraphState]` (single positional `state` param, any return), which is
    # exactly what every add_node overload accepts at runtime.
    graph.add_node("ceo_agent", _halt_on_entry("ceo_agent", ceo_agent_node))  # type: ignore[call-overload]
    graph.add_node("market_analyst", _halt_on_entry("market_analyst", market_analyst_node))  # type: ignore[call-overload]
    graph.add_node(
        "strategy_generator", _halt_on_entry("strategy_generator", strategy_generator_node)
    )  # type: ignore[call-overload]
    graph.add_node(
        "python_code_generator",
        _halt_on_entry("python_code_generator", python_code_generator_node),
    )  # type: ignore[call-overload]
    graph.add_node("compliance", _halt_on_entry("compliance", compliance_node))  # type: ignore[call-overload]
    graph.add_node("python_validator", _halt_on_entry("python_validator", python_validator_node))  # type: ignore[call-overload]
    graph.add_node("backtesting", _halt_on_entry("backtesting", backtesting_node))  # type: ignore[call-overload]
    graph.add_node("evaluator", _halt_on_entry("evaluator", evaluator_node))  # type: ignore[call-overload]
    graph.add_node("memory_ingest", _halt_on_entry("memory_ingest", memory_ingest_node))  # type: ignore[call-overload]
    graph.add_node("optimization", _halt_on_entry("optimization", optimization_node))  # type: ignore[call-overload]
    graph.add_node("risk_manager", _halt_on_entry("risk_manager", risk_manager_node))  # type: ignore[call-overload]
    graph.add_node("deployment", _halt_on_entry("deployment", deployment_node))  # type: ignore[call-overload]

    graph.set_entry_point("ceo_agent")
    graph.add_edge("ceo_agent", "market_analyst")
    graph.add_edge("market_analyst", "strategy_generator")
    graph.add_edge("strategy_generator", "python_code_generator")
    graph.add_edge("python_code_generator", "compliance")
    graph.add_conditional_edges(
        "compliance",
        route_after_compliance,
        {"python_validator": "python_validator", "END": END},
    )
    graph.add_conditional_edges(
        "python_validator",
        route_after_validation,
        {
            "backtesting": "backtesting",
            "python_code_generator": "python_code_generator",
            "END": END,
        },
    )
    graph.add_edge("backtesting", "evaluator")
    graph.add_conditional_edges(
        "evaluator",
        route_after_evaluation,
        {"optimization": "optimization", "memory_ingest": "memory_ingest"},
    )
    graph.add_conditional_edges(
        "memory_ingest",
        route_after_memory_ingest,
        {"strategy_generator": "strategy_generator", "ceo_agent": "ceo_agent"},
    )
    graph.add_edge("optimization", "risk_manager")
    graph.add_edge("risk_manager", "deployment")
    graph.add_edge("deployment", END)

    return graph.compile()
