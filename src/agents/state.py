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


class OptimizationResult(StrictModel):
    """Optimization Agent output (AGT-007) — WFO + Monte Carlo + Optuna sweep."""

    passed: bool
    best_params: dict[str, float] = Field(default_factory=dict)
    robustness_score: float | None = None  # Monte Carlo P95 max drawdown
    notes: str | None = None


class RiskAssessment(StrictModel):
    """Risk Manager Agent output (AGT-008) — advisory only; the hardcoded risk engine
    (src/engine/risk/) retains final veto power, this only adds a narrative alongside it."""

    decision: Literal["Approve", "ApproveWithRestrictions", "Reject"]
    kill_switch_tripped: bool
    correlation_passed: bool | None = None  # None = check not applicable/unavailable
    naked_options_checked: bool  # False -- no structured leg data existed to check against
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
    compliance_verdict: ComplianceVerdict | None = None
    validation_result: ValidationResult | None = None
    backtest_metrics: BacktestMetrics | None = None
    equity_curve: list[EquityCurvePoint] = Field(default_factory=list)
    evaluation_verdict: EvaluationVerdict | None = None
    optimization_result: OptimizationResult | None = None
    risk_assessment: RiskAssessment | None = None
    deployment_recommendation: DeploymentRecommendation | None = None

    # Retry/escalation counters enforcing the business rules from Phase_9/Phase_4:
    code_validation_retry_count: int = 0  # max 3, Code_Validation_Loop
    strategy_rejection_count: int = 0  # max 5 consecutive, then escalate to CEO
    errors: list[str] = Field(default_factory=list)
