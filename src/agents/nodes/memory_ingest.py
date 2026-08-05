"""Memory Ingest node (AGT-009's second real call site) — REL-025.

`src/memory/strategy_memory.py::ingest_strategy_outcome` has been real and tested since Phase 2,
but nothing in the live pipeline ever called it -- the system generated and rejected strategies
without ever learning from the rejection (`src/agents/nodes/memory_agent.py` is a different real
agent, the weekend batch-archival job over *already-ingested* points, not the ingestion path
itself). This node closes that gap: wired into `src/agents/graph.py`'s FAIL branch, between
`evaluator` and both of its FAIL-branch targets (`strategy_generator`'s retry loop and the
5-rejection `ceo_agent` escalation), so every rejected strategy gets a real Qdrant point before
the graph decides what to do next.

`strategy_id`/`strategy_version_id` are `state.thread_id`/`state.strategy_version_id`, not real
Postgres UUIDs -- see `TradingOSGraphState.strategy_version_id`'s own docstring for why (nodes are
pure functions with no DB session, matching this codebase's established convention). Qdrant's own
`trading_strategies` payload schema (DB-023) never enforced these as foreign keys, and this
codebase's existing tests already treat them as opaque traceability strings, not real UUIDs.
"""

from src.agents.state import TradingOSGraphState
from src.memory.strategy_memory import ingest_strategy_outcome


def memory_ingest_node(state: TradingOSGraphState) -> dict[str, object]:
    if state.strategy_logic is None:
        raise ValueError("memory_ingest_node requires state.strategy_logic")
    if state.python_code is None:
        raise ValueError("memory_ingest_node requires state.python_code")
    if state.backtest_metrics is None:
        raise ValueError("memory_ingest_node requires state.backtest_metrics")
    if state.evaluation_verdict is None or state.evaluation_verdict.verdict != "FAIL":
        raise ValueError("memory_ingest_node requires a FAIL state.evaluation_verdict")

    strategy_version_id = (
        state.strategy_version_id or f"{state.thread_id}-v{state.python_code.version_no}"
    )
    failure_reason = "; ".join(state.evaluation_verdict.failure_reasons) or None

    ingest_strategy_outcome(
        strategy_id=state.thread_id,
        strategy_version_id=strategy_version_id,
        hypothesis=state.strategy_logic.hypothesis,
        code=state.python_code.code,
        asset_class=state.strategy_logic.asset_class,
        sharpe_ratio=state.backtest_metrics.sharpe_ratio,
        max_drawdown=state.backtest_metrics.max_drawdown,
        status="deprecated",
        failure_reason=failure_reason,
    )
    return {}
