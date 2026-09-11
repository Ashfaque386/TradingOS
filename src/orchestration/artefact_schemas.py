"""Typed artefact schemas for the organisation layer (spec T012, data-model.md section 5).

Every ``ResultArtefact.payload`` validates against the Pydantic model registered here for its
``artefact_type`` (FR-030 "typed"). Where the existing research pipeline already has a model
(``src/agents/state.py``) it is reused verbatim; the remaining artefact types get lightweight
models defined here.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from src.agents.state import (
    BacktestMetrics,
    ComplianceVerdict,
    DeploymentRecommendation,
    EvaluationVerdict,
    MarketContext,
    OptimizationResult,
    PythonCode,
    ResearchDirective,
    RiskAssessment,
    StrategyLogic,
    ValidationResult,
)


class _Artefact(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NewsDigest(_Artefact):
    """AGT-013 output (FR-040)."""

    headlines: list[dict[str, Any]]
    affected_symbols: list[str] = []
    affected_sectors: list[str] = []
    urgency: str = "Routine"
    source_count: int = 0
    reduced_coverage: bool = False


class SentimentReport(_Artefact):
    """AGT-014 output (FR-041)."""

    per_symbol: dict[str, float] = {}
    per_sector: dict[str, float] = {}
    trending_topics: list[str] = []
    confidence: float = 0.0
    sample_size: int = 0


class PortfolioRiskReport(_Artefact):
    """AGT-016 / risk-context output (FR-043)."""

    total_capital: float | None = None
    used_capital: float | None = None
    available_to_trade: float | None = None
    exposures: dict[str, float] = {}
    highest_risk_positions: list[dict[str, Any]] = []
    notes: str = ""


class AllocationPlan(_Artefact):
    per_strategy_weight: dict[str, float] = {}
    rationale: str = ""
    correlation_summary: dict[str, Any] = {}


class ResearchContext(_Artefact):
    """Assembled organisational context handed to the research sub-graph (FR-042/044)."""

    market_regime: str | None = None
    # Real Market Analyst output ranks sectors (list[str]), it doesn't score them numerically --
    # this used to be typed `dict[str, float]` ("sector_strengths") and always read the wrong key
    # off MarketContext (which has no such field), so it silently stayed `{}` for both the old
    # placeholder and the real handler alike. Fixed alongside the real handler wiring (T113).
    sector_rankings: list[str] = []
    news_summary: str = ""
    sentiment: dict[str, float] = {}
    portfolio_exposure: dict[str, float] = {}
    risk_posture: str | None = None
    coverage: str = "full"  # "full" | "reduced"
    missing_inputs: list[str] = []


class OptionStrategyProposal(_Artefact):
    legs: list[dict[str, Any]]
    expiry: str | None = None
    rationale: str = ""
    max_loss: float | None = None
    max_profit: float | None = None


class CeoSynthesis(_Artefact):
    """The CEO's plain-language synthesis handed back to the requester (FR-132)."""

    summary: str
    recommendation: str = ""
    key_findings: list[str] = []
    next_step: str | None = None


class AdHocAnalysis(_Artefact):
    """Result of an agent-driven ad-hoc analysis (FR-130)."""

    question: str
    answer: str
    supporting_data: dict[str, Any] = {}


ARTEFACT_SCHEMA_REGISTRY: dict[str, type[BaseModel]] = {
    "ResearchDirective": ResearchDirective,
    "MarketContext": MarketContext,
    "NewsDigest": NewsDigest,
    "SentimentReport": SentimentReport,
    "PortfolioRiskReport": PortfolioRiskReport,
    "AllocationPlan": AllocationPlan,
    "ResearchContext": ResearchContext,
    "StrategyLogic": StrategyLogic,
    "OptionStrategyProposal": OptionStrategyProposal,
    "PythonCode": PythonCode,
    "ValidationReport": ValidationResult,
    "ComplianceReport": ComplianceVerdict,
    "BacktestMetrics": BacktestMetrics,
    "OptimizationReport": OptimizationResult,
    "RiskReport": RiskAssessment,
    "EvaluationReport": EvaluationVerdict,
    "DeploymentRecommendation": DeploymentRecommendation,
    "CeoSynthesis": CeoSynthesis,
    "AdHocAnalysis": AdHocAnalysis,
}


class UnknownArtefactTypeError(ValueError):
    pass


def validate_payload(artefact_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate ``payload`` against the registered schema; returns the normalised dict.

    Raises ``UnknownArtefactTypeError`` for an unregistered type and ``pydantic.ValidationError``
    for a payload that does not match the schema (FR-030).
    """
    model = ARTEFACT_SCHEMA_REGISTRY.get(artefact_type)
    if model is None:
        raise UnknownArtefactTypeError(artefact_type)
    return model.model_validate(payload).model_dump(mode="json")
