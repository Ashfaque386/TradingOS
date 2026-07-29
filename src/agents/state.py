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


class MLTrainingRequest(StrictModel):
    """ML Agent input (AGT-017, REL-008 E8.6) -- set by the caller (POST /ml/models/train) before
    invoking build_supervised_training_graph(); ml_agent_node executes this deterministically,
    it never chooses its own training target."""

    model_type: Literal["LightGBM", "TFT-PyTorch"]
    task: Literal["classification", "regression"]
    symbols: list[str]
    window_start: str
    window_end: str
    trigger_reason: Literal["manual", "weekly_scheduled", "drift_triggered"] = "manual"


class MLTrainingResult(StrictModel):
    """ML Agent output (AGT-017)."""

    ml_model_id: str
    mlflow_run_id: str
    model_type: Literal["LightGBM", "TFT-PyTorch"]
    metrics: dict[str, float] = Field(default_factory=dict)
    baseline_comparison: dict[str, float] = Field(default_factory=dict)
    artifact_path: str
    git_commit_hash: str
    training_data_hash: str
    narrative: str


class RLTrainingRequest(StrictModel):
    """RL Agent input (AGT-018, REL-008 E8.6)."""

    algorithm: Literal["PPO", "SAC"]
    symbols: list[str]
    window_start: str
    window_end: str
    total_timesteps: int
    seeds: list[int]
    trigger_reason: Literal["manual", "weekly_scheduled", "drift_triggered"] = "manual"


class RLTrainingResult(StrictModel):
    """RL Agent output (AGT-018)."""

    ml_model_id: str
    mlflow_run_id: str
    algorithm: Literal["PPO", "SAC"]
    reward_mean_by_seed: dict[str, float] = Field(default_factory=dict)
    reward_variance_cv: float
    stability_passed: bool
    backtest_sharpe: float | None = None
    artifact_path: str
    narrative: str


class ModelEvaluationVerdict(StrictModel):
    """Model Evaluator Agent output (AGT-019, REL-008 E8.6) -- a recommendation only. Never
    itself calls POST /ml/models/{id}/promote; promotion is always a separate, human-role-gated
    (PortfolioManager/SystemAdministrator) call, matching AGT-017/018's own "never promote
    yourself" prompt lines and this project's standing human-in-the-loop rule."""

    decision: Literal["Promote", "Reject", "Shadow-Test"]
    candidate_ml_model_id: str
    production_ml_model_id: str | None = None
    metric_deltas: dict[str, float] = Field(default_factory=dict)
    confidence_score: float = Field(ge=0.0, le=1.0)
    comparison_report: str


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

    # REL-008 E8.6: ML/RL training + evaluation -- set by src/agents/ml_graph.py's two small
    # graphs, not the main graph above (model training isn't part of every strategy-generation
    # run, see src/agents/ml_graph.py's module docstring for why it's a separate graph).
    ml_training_request: MLTrainingRequest | None = None
    ml_training_result: MLTrainingResult | None = None
    rl_training_request: RLTrainingRequest | None = None
    rl_training_result: RLTrainingResult | None = None
    model_evaluation_verdict: ModelEvaluationVerdict | None = None

    # Retry/escalation counters enforcing the business rules from Phase_9/Phase_4:
    code_validation_retry_count: int = 0  # max 3, Code_Validation_Loop
    strategy_rejection_count: int = 0  # max 5 consecutive, then escalate to CEO
    errors: list[str] = Field(default_factory=list)
