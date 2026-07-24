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


class TradingOSGraphState(StrictModel):
    """The shared state object LangGraph threads through every node in the graph."""

    thread_id: str
    research_directive: ResearchDirective | None = None
    market_context: MarketContext | None = None
    strategy_logic: StrategyLogic | None = None
    python_code: PythonCode | None = None
    validation_result: ValidationResult | None = None
    backtest_metrics: BacktestMetrics | None = None
    evaluation_verdict: EvaluationVerdict | None = None

    # Retry/escalation counters enforcing the business rules from Phase_9/Phase_4:
    code_validation_retry_count: int = 0  # max 3, Code_Validation_Loop
    strategy_rejection_count: int = 0  # max 5 consecutive, then escalate to CEO
    errors: list[str] = Field(default_factory=list)
