import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, UUIDPKMixin


class Strategy(Base, UUIDPKMixin, TimestampMixin):
    """DB-005. Lifecycle: Ideation->Coding->Backtesting->PaperTrading->Live->Deprecated -- the
    Kanban columns in Phase_7_Frontend_Architecture.md §2.3, and what
    src/api/routers/agents.py's `_execute_graph_run` actually sets as each LangGraph node
    completes (the original docstring here named a different string set --
    Draft/Optimizing/RiskReview/Paper -- that nothing in the codebase ever wrote; only "Live" is
    load-bearing today, read by src/api/routers/portfolio.py's Sharpe calc, and is preserved
    exactly)."""

    __tablename__ = "strategies"

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("strategy_versions.id", use_alter=True, name="fk_strategies_current_version_id"),
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    hypothesis: Mapped[str | None] = mapped_column(Text)
    asset_class: Mapped[str] = mapped_column(String(10), nullable=False)
    style: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="Ideation")
    max_drawdown_limit: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    created_by_agent: Mapped[str] = mapped_column(String(50), default="StrategyGeneratorAgent")
    # StrategyLogic.universe (src/agents/state.py) -- which symbol(s) the strategy trades.
    # Nullable: rows persisted before this column existed, or a strategy whose universe was
    # never captured, have no universe rather than a fabricated one.
    universe: Mapped[list[str] | None] = mapped_column(ARRAY(String(30)))
    updated_at: Mapped[datetime | None]
    # REL-044: the rest of StrategyLogic (src/agents/state.py) -- the Strategy Generator Agent
    # computes these on every run, but until this migration only hypothesis/asset_class/style/
    # universe were ever copied onto this row; entry/exit/stop/take-profit/position-sizing/
    # confidence were silently discarded (see src/api/routers/agents.py::_persist_strategy_
    # progress). Nullable, not backfilled -- a row created before this migration has no real
    # logic text to recover, same convention as `universe` above.
    entry_conditions: Mapped[str | None] = mapped_column(Text)
    exit_conditions: Mapped[str | None] = mapped_column(Text)
    stop_loss: Mapped[str | None] = mapped_column(Text)
    take_profit: Mapped[str | None] = mapped_column(Text)
    position_sizing: Mapped[str | None] = mapped_column(Text)
    confidence_score: Mapped[float | None] = mapped_column(Numeric(6, 3))
    # REL-044: the CEO Agent's ResearchDirective and Market Analyst's MarketContext (both
    # src/agents/state.py) that led to this strategy being proposed -- real, LLM-authored "why"
    # context that previously existed only transiently in AgentRun.output_state, never on the
    # Strategy row itself and never returned by any endpoint. Full model_dump(mode="json") of
    # each Pydantic object, not a hand-picked subset -- matches this codebase's own JSONB-
    # sub-object precedent (BacktestResult.option_legs/trades/walk_forward_results below).
    research_context: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    market_context: Mapped[dict[str, object] | None] = mapped_column(JSONB)


class StrategyVersion(Base, UUIDPKMixin, TimestampMixin):
    """DB-006. Immutable code revision per Code Gen/Validator loop."""

    __tablename__ = "strategy_versions"
    __table_args__ = (UniqueConstraint("strategy_id", "version_no"),)

    strategy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategies.id"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    python_code: Mapped[str] = mapped_column(Text, nullable=False)
    validation_status: Mapped[str] = mapped_column(String(20), default="Pending")
    validator_feedback: Mapped[str | None] = mapped_column(Text)
    qdrant_point_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # REL-035: the Options Strategy Agent's real, chain-grounded legs (list of {symbol,
    # option_type, strike, side, quantity} dicts) and the real expiry they were grounded
    # against -- NULL for an equity strategy, or an F&O strategy whose grounding degraded (see
    # src/agents/nodes/options_strategy_agent.py). Not retroactive: a row created before this
    # migration has no real legs to backfill.
    option_legs: Mapped[list[dict[str, float | str | int]] | None] = mapped_column(JSONB)
    option_expiry: Mapped[date | None]
    # REL-044: the Options Strategy Agent's real, LLM-authored rationale for these legs
    # (OptionsStrategyProposal.rationale, src/agents/nodes/options_strategy_agent.py) --
    # computed on every F&O run but previously discarded before it even reached
    # TradingOSGraphState (the node's own return dict omitted it). NULL for equity strategies
    # and for F&O rows created before this migration.
    option_rationale: Mapped[str | None] = mapped_column(Text)


class BacktestResult(Base, UUIDPKMixin, TimestampMixin):
    """DB-007. VectorBT performance metrics per strategy version."""

    __tablename__ = "backtest_results"

    strategy_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategy_versions.id"), nullable=False
    )
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id")
    )
    date_from: Mapped[date] = mapped_column(nullable=False)
    date_to: Mapped[date] = mapped_column(nullable=False)
    initial_capital: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    sharpe_ratio: Mapped[float | None] = mapped_column(Numeric(6, 3))
    sortino_ratio: Mapped[float | None] = mapped_column(Numeric(6, 3))
    calmar_ratio: Mapped[float | None] = mapped_column(Numeric(8, 3))
    max_drawdown: Mapped[float | None] = mapped_column(Numeric(6, 3))
    cagr: Mapped[float | None] = mapped_column(Numeric(6, 3))
    win_rate: Mapped[float | None] = mapped_column(Numeric(5, 2))
    profit_factor: Mapped[float | None] = mapped_column(Numeric(6, 3))
    expectancy: Mapped[float | None] = mapped_column(Numeric(14, 2))
    total_trades: Mapped[int | None] = mapped_column(Integer)
    # Monte Carlo simulation (Phase 3 Epic E3.3, Phase_6_Trading_Engine_Design.md §3): "The 95th
    # percentile Max Drawdown from the Monte Carlo simulation is used as the absolute risk
    # metric, not the historical Max Drawdown" -- stored alongside the historical max_drawdown
    # above (not replacing it) so both are auditable together.
    monte_carlo_p95_max_drawdown: Mapped[float | None] = mapped_column(Numeric(6, 3))
    recommendation: Mapped[str | None] = mapped_column(String(20))
    equity_curve_path: Mapped[str | None] = mapped_column(String(255))
    # REL-022: the real per-trade ledger (PMPT-004 v3's "trades" field). NULL only for rows
    # created before this migration ran -- every row created after it gets a real list, possibly
    # empty (a pre-v3-contract strategy and a real v3 strategy with zero closed trades in the
    # window both parse to [], the same missing-vs-malformed limitation
    # backtest_runner.py::_extract_equity_curve already has). Not retroactively backfilled for
    # older rows. See backtest_runner.py's Trade dataclass for the 8-field shape each entry has.
    trades: Mapped[list[dict[str, float | str]] | None] = mapped_column(JSONB)
    # REL-024: real Walk-Forward Optimization window summaries (Phase_6 §3), from
    # src/engine/optimization/walk_forward_adapter.py -- NULL for rows created before this
    # migration ran, or a real run with too little entries_exits/close_curve history for even
    # one rolling window (see that module's own docstring). See
    # WalkForwardWindowSummary for the per-window shape each list entry has.
    walk_forward_results: Mapped[list[dict[str, object]] | None] = mapped_column(JSONB)
    # REL-005: extends this one row to carry the whole downstream pipeline's outcome for the
    # run it belongs to (Evaluator/Optimization/RiskManager/Deployment) -- Phase_11's DB design
    # doc has no dedicated tables for these, and one backtest_results row per run is already the
    # natural anchor, so new tables weren't invented for them.
    evaluation_verdict: Mapped[str | None] = mapped_column(String(10))
    evaluation_failure_reasons: Mapped[list[str] | None] = mapped_column(JSONB)
    optimization_best_params: Mapped[dict[str, float] | None] = mapped_column(JSONB)
    optimization_robustness_score: Mapped[float | None] = mapped_column(Numeric(6, 3))
    risk_assessment_passed: Mapped[bool | None] = mapped_column(Boolean)
    risk_assessment_notes: Mapped[str | None] = mapped_column(Text)
    deployment_recommendation: Mapped[str | None] = mapped_column(String(20))
    deployment_rationale: Mapped[str | None] = mapped_column(Text)


class StrategySuggestion(Base, UUIDPKMixin, TimestampMixin):
    """REL-048. A human-submitted free-text suggestion against a real Strategy, reviewed by a
    lightweight LLM step (src/agents/nodes/suggestion_reviewer.py) and, if judged sound,
    implemented by re-entering the real agent pipeline (build_suggestion_regeneration_graph(),
    src/agents/graph.py) rather than a surgical field edit -- the resulting StrategyVersion/
    BacktestResult come out shaped identically to any other run. `resulting_version_id` is only
    ever set once `status` reaches `Applied`."""

    __tablename__ = "strategy_suggestions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('Pending', 'Reviewing', 'Rejected', 'Applied')",
            name="ck_suggestion_status",
        ),
    )

    strategy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategies.id"), nullable=False, index=True
    )
    submitted_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    suggestion_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="Pending")
    ai_verdict: Mapped[str | None] = mapped_column(Text)
    ai_reasoning: Mapped[str | None] = mapped_column(Text)
    resulting_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategy_versions.id")
    )
    reviewed_at: Mapped[datetime | None]
