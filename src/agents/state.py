"""Pydantic V2 state models exchanged between LangGraph nodes (Phase 2 Epic E2.1).

Mirrors the state diagram in Phase_3_Low_Level_Design.md §2: Research -> Strategy Generator ->
Code Gen/Validator loop -> Backtest/Evaluator loop -> Optimization -> Risk -> Deployment.
Every model uses `extra="forbid"` so a malformed or unexpected field is rejected at
construction time rather than silently passed downstream between agents.
"""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MarketRegime = Literal[
    "Bullish", "Bearish", "Sideways", "High Volatility", "Low Volatility", "Risk-On", "Risk-Off"
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ResearchDirective(StrictModel):
    """CEO Agent output (AGT-001) — the daily Executive Research Directive."""

    market_regime: MarketRegime
    priority_sectors: list[str]
    strategy_themes: list[str]
    risk_tolerance: Literal["Low", "Medium", "High"]
    participating_agents: list[str]
    expected_outcomes: str
    is_fallback_directive: bool = False  # True if issued due to global data API failure
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MarketContext(StrictModel):
    """Market Analyst Agent output (AGT-002)."""

    market_regime: MarketRegime
    sector_rankings: list[str]
    volatility_assessment: str
    macro_outlook: str
    confidence_score: float = Field(ge=0.0, le=1.0)
    insights: list[str]


class StrategyOptionLeg(StrictModel):
    """REL-016 E16.3 (GLH-09): one option leg a strategy declares it will trade -- the
    Pydantic-side twin of `src/engine/risk/naked_options_scanner.py::OptionLeg` (a plain
    dataclass there, matching that module's own dependency-light "hardcoded engine" style; this
    twin exists so `StrategyLogic.model_json_schema()` -- already fed straight into the Strategy
    Generator Agent's prompt -- teaches the LLM the exact shape to emit, the same two-classes-
    same-fields precedent this codebase already has for EquityCurvePoint/ComplianceVerdict."""

    symbol: str
    option_type: Literal["CE", "PE"]
    strike: float
    side: Literal["buy", "sell"]
    quantity: int


class StrategyLogic(StrictModel):
    """Strategy Generator Agent output (AGT-003) — plain-text mathematical trading logic."""

    hypothesis: str
    asset_class: Literal["Equity", "F&O"]
    style: Literal["Intraday", "Swing"]
    universe: list[str]
    entry_conditions: str
    exit_conditions: str
    stop_loss: str
    take_profit: str
    position_sizing: str
    confidence_score: float = Field(ge=0.0, le=1.0)
    # REL-016 E16.3 (GLH-09): populated by the Strategy Generator Agent only for "F&O" strategies
    # (prompt v2, PMPT-029) -- gives the hardcoded naked-options scanner real, declared legs to
    # check instead of the honest-but-permanent skip this codebase had before (risk_manager.py/
    # compliance_checker.py's own module docstrings named this exact gap). None for "Equity"
    # strategies, where there is nothing to declare.
    option_legs: list[StrategyOptionLeg] | None = None


class PythonCode(StrictModel):
    """Python Code Generator Agent output (AGT-004)."""

    code: str
    strategy_id: str | None = None
    version_no: int = 1


class ValidationResult(StrictModel):
    """Python Validator Agent output (AGT-005). Loops back to Code Generator on Fail, up to 3x."""

    status: Literal["Pass", "Fail"]
    severity: Literal["Low", "Medium", "High", "Critical"] | None = None
    error_trace: str | None = None
    feedback: str | None = None


class BacktestMetrics(StrictModel):
    """Backtesting Agent output (AGT-006)."""

    sharpe_ratio: float
    sortino_ratio: float | None = None
    calmar_ratio: float | None = None
    max_drawdown: float
    cagr: float | None = None
    win_rate: float | None = None
    profit_factor: float | None = None
    expectancy: float | None = None
    total_trades: int | None = None


class EvaluationVerdict(StrictModel):
    """Evaluator Agent output (AGT-011) — gatekeeper of the Backtest_Loop."""

    verdict: Literal["PASS", "FAIL"]
    failure_reasons: list[str] = Field(default_factory=list)
    feedback_for_strategy_generator: str | None = None


class EquityCurvePoint(StrictModel):
    """One daily portfolio-equity sample from a real backtest run (Backtesting Agent, AGT-006) --
    carried in state so the Optimization Agent's Monte Carlo re-sampling (AGT-007) has real
    return data to work with, without re-running the backtest a second time."""

    date: str
    equity: float


class EntryExitSignal(StrictModel):
    """REL-024: one day's real entry/exit signal from the sandboxed strategy's own
    `Portfolio.from_signals` call (PMPT-004 v3's `entries_exits`, REL-022) -- carried in state so
    the Optimization Agent's Walk-Forward adapter has the real signal series to re-run against
    rolling windows, without re-executing the LLM's sandboxed code once per window."""

    date: str
    entry: bool
    exit: bool


class ClosePricePoint(StrictModel):
    """REL-024: one day's real OHLCV close price for the backtest's symbol/window -- carried in
    state alongside `EntryExitSignal` so Walk-Forward has real prices to re-simulate against,
    not just the strategy's own equity curve (which is a function of its P&L, not the raw
    market)."""

    date: str
    close: float


class OptimizationResult(StrictModel):
    """Optimization Agent output (AGT-007) — WFO + Monte Carlo + Optuna sweep."""

    passed: bool
    best_params: dict[str, float] = Field(default_factory=dict)
    robustness_score: float | None = None  # Monte Carlo P95 max drawdown
    # REL-024: per-window Walk-Forward summaries (src/engine/optimization/walk_forward_adapter.py
    # ::WalkForwardWindowSummary, serialized), empty when there wasn't enough real data for even
    # one rolling window -- see that module's own docstring for why, not fabricated as a pass.
    walk_forward_results: list[dict[str, object]] = Field(default_factory=list)
    walk_forward_passed: bool | None = None  # None: WFO didn't run at all (see notes)
    notes: str | None = None


class RiskAssessment(StrictModel):
    """Risk Manager Agent output (AGT-008) — advisory only; the hardcoded risk engine
    (src/engine/risk/) retains final veto power, this only adds a narrative alongside it."""

    decision: Literal["Approve", "ApproveWithRestrictions", "Reject"]
    kill_switch_tripped: bool
    correlation_passed: bool | None = None  # None = check not applicable/unavailable
    naked_options_checked: bool  # False -- no structured leg data existed to check against
    # REL-034: real inverse-volatility position sizing (src/engine/risk/position_sizing.py),
    # computed against the Paper Trading Account's own live equity once state.account_capital
    # is populated -- None (not fabricated) whenever no real capital figure was threaded in.
    position_sizing_shares: int | None = None
    narrative: str


class ComplianceVerdict(StrictModel):
    """Compliance Agent output (AGT-020, PMPT-038/039, REL-006 E6.1). Deterministic decision --
    delegates entirely to src/engine/risk/compliance_checker.py's evaluate_compliance(); the
    narrative field alone is LLM-generated (advisory only, same "hardcoded engine has final
    veto power" convention as RiskAssessment)."""

    verdict: Literal["Pass", "Block"]
    violations: list[str] = Field(default_factory=list)
    naked_options_checked: bool
    position_limit_checked: bool
    circuit_filter_checked: bool
    narrative: str


class DeploymentRecommendation(StrictModel):
    """Deployment Agent output (AGT-012) — a recommendation only. Never itself executes a
    transition to Live; Business Rule 3 (human-in-the-loop) remains the RBAC-gated
    /strategies/{id}/promote endpoint, which this agent never calls."""

    recommended_status: Literal["PaperTrading", "Reject"]
    rationale: str


# REL-008's ML/RL state models (MLTrainingRequest/Result, RLTrainingRequest/Result,
# ModelEvaluationVerdict, for AGT-017/018/019) were removed 2026-07-30 alongside the rest of the
# ML/RL platform (Phase 5), disabled pending a host resource upgrade -- see
# Phase_5_Machine_Learning_Architecture.md's own status banner. Re-add when Phase 5 is
# re-implemented.


class TradingOSGraphState(StrictModel):
    """The shared state object LangGraph threads through every node in the graph."""

    thread_id: str
    research_directive: ResearchDirective | None = None
    market_context: MarketContext | None = None
    strategy_logic: StrategyLogic | None = None
    python_code: PythonCode | None = None
    # REL-025: a real, stable identifier for this run's current code version -- set by
    # python_code_generator_node from thread_id+version_no (no node has a real Postgres
    # StrategyVersion.id to use; nodes are pure functions with no DB session, per this
    # codebase's own established convention -- see backtesting_node's own docstring). Used by
    # memory_ingest_node as Qdrant traceability metadata, not an enforced foreign key.
    strategy_version_id: str | None = None
    compliance_verdict: ComplianceVerdict | None = None
    validation_result: ValidationResult | None = None
    backtest_metrics: BacktestMetrics | None = None
    equity_curve: list[EquityCurvePoint] = Field(default_factory=list)
    # REL-024: populated by backtesting_node alongside equity_curve, from the same real backtest
    # run's outcome.entries_exits/outcome.close_curve -- the Optimization Agent's Walk-Forward
    # adapter input.
    entries_exits: list[EntryExitSignal] = Field(default_factory=list)
    close_curve: list[ClosePricePoint] = Field(default_factory=list)
    evaluation_verdict: EvaluationVerdict | None = None
    optimization_result: OptimizationResult | None = None
    risk_assessment: RiskAssessment | None = None
    deployment_recommendation: DeploymentRecommendation | None = None
    # REL-034: the Paper Trading Account's real live equity (starting capital + realized P&L -
    # margin blocked), injected by src/api/routers/agents.py::_execute_graph_run before the
    # graph runs -- None (not fabricated) whenever no seeded Paper account exists yet. Closes
    # the long-documented gap risk_manager.py's own module docstring names: position sizing
    # "still needs real account capital, which isn't threaded into TradingOSGraphState anywhere."
    account_capital: float | None = None

    # Retry/escalation counters enforcing the business rules from Phase_9/Phase_4:
    code_validation_retry_count: int = 0  # max 3, Code_Validation_Loop
    strategy_rejection_count: int = 0  # max 5 consecutive, then escalate to CEO
    errors: list[str] = Field(default_factory=list)
