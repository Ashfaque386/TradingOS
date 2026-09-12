"""CEO decisions & structured collaboration records (spec T056/T057/T058, FR-020..023, SC-014).

Two things live here:

- ``detect_conflict`` -- a *deterministic* comparator over this run's result artefacts. When two
  artefacts genuinely oppose each other (bullish market vs negative aggregate sentiment; a
  ``Reject`` risk verdict against a strategy that means to proceed; a compliance ``Block`` against
  a strategy that means to proceed) it returns a ``Conflict``; ``resolve_conflict`` then records a
  ``resolve_conflict`` ``OrganizationalDecision`` (summary, reason, supporting inputs, next step)
  and emits ``ceo.conflict_detected`` + ``ceo.decision.created`` before the run may continue.
- ``record_decision`` and the ``record_*`` collaboration helpers -- delegation, hand-off, review
  request/result and escalation are written as typed ``OrganizationalDecision`` /
  ``OrganizationalEvent`` rows, never as free-form prompt text (FR-020).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.orchestration import OrganizationalDecision, OrganizationRun, ResultArtefact
from src.orchestration import events
from src.orchestration.enums import DecisionType

logger = structlog.get_logger(__name__)

_BULLISH = {"Bullish", "Risk-On"}
_BEARISH = {"Bearish", "Risk-Off"}
_PROCEED_ARTEFACTS = {"StrategyLogic", "AllocationPlan", "OptionStrategyProposal", "PythonCode"}
_SENTIMENT_THRESHOLD = 0.2


@dataclass
class Conflict:
    kind: str
    description: str
    artefact_ids: list[str]
    severity: str = "medium"  # "medium" | "high"
    escalate_to_role: str | None = None
    next_step: str = "Proceed with the CEO's recorded resolution."
    supporting_agents: list[str] = field(default_factory=list)


def _aggregate_sentiment(payload: dict[str, object]) -> float | None:
    vals: list[float] = []
    for bucket in ("per_symbol", "per_sector"):
        raw = payload.get(bucket)
        if isinstance(raw, dict):
            vals.extend(float(v) for v in raw.values() if isinstance(v, int | float))
    if not vals:
        return None
    return sum(vals) / len(vals)


def detect_conflict(artefacts: list[ResultArtefact]) -> Conflict | None:
    """First genuine opposition found, or ``None``. Deterministic -- no LLM."""
    by_type: dict[str, ResultArtefact] = {}
    for a in artefacts:
        by_type.setdefault(a.artefact_type, a)

    market = by_type.get("MarketContext")
    sentiment = by_type.get("SentimentReport")
    if market is not None and sentiment is not None:
        regime = str(market.payload.get("market_regime") or "")
        agg = _aggregate_sentiment(dict(sentiment.payload))
        if agg is not None:
            if regime in _BULLISH and agg <= -_SENTIMENT_THRESHOLD:
                return Conflict(
                    kind="market_vs_sentiment",
                    description=(
                        f"Market regime is {regime!r} but aggregate sentiment is {agg:+.2f}."
                    ),
                    artefact_ids=[str(market.id), str(sentiment.id)],
                    severity="medium",
                    supporting_agents=["market_analyst", "sentiment_agent"],
                )
            if regime in _BEARISH and agg >= _SENTIMENT_THRESHOLD:
                return Conflict(
                    kind="market_vs_sentiment",
                    description=(
                        f"Market regime is {regime!r} but aggregate sentiment is {agg:+.2f}."
                    ),
                    artefact_ids=[str(market.id), str(sentiment.id)],
                    severity="medium",
                    supporting_agents=["market_analyst", "sentiment_agent"],
                )

    proceed = next((by_type[t] for t in _PROCEED_ARTEFACTS if t in by_type), None)

    risk = by_type.get("RiskReport")
    if risk is not None and proceed is not None and risk.payload.get("decision") == "Reject":
        return Conflict(
            kind="risk_vs_proposal",
            description="Risk assessment is 'Reject' while a strategy proposal means to proceed.",
            artefact_ids=[str(risk.id), str(proceed.id)],
            severity="high",
            escalate_to_role="RiskManager",
            next_step="Do not proceed; risk 'Reject' stands unless a human overrides.",
            supporting_agents=["risk_manager"],
        )

    compliance = by_type.get("ComplianceReport")
    if (
        compliance is not None
        and proceed is not None
        and compliance.payload.get("verdict") == "Block"
    ):
        return Conflict(
            kind="compliance_vs_proposal",
            description="Compliance verdict is 'Block' while a strategy proposal means to proceed.",
            artefact_ids=[str(compliance.id), str(proceed.id)],
            severity="high",
            escalate_to_role="RiskManager",
            next_step="Do not proceed; compliance 'Block' is terminal for this proposal.",
            supporting_agents=["compliance"],
        )
    return None


def _portfolio_artefact_ids(session: Session, run_id: uuid.UUID) -> list[str]:
    rows = session.scalars(
        select(ResultArtefact.id).where(
            ResultArtefact.run_id == run_id,
            ResultArtefact.artefact_type == "PortfolioRiskReport",
        )
    ).all()
    return [str(r) for r in rows]


def record_decision(
    session: Session,
    run: OrganizationRun,
    *,
    decision_type: DecisionType,
    summary: str,
    reason: str,
    supporting_input_artefact_ids: list[str] | None = None,
    supporting_agents: list[str] | None = None,
    next_step: str | None = None,
    escalated_to_role: str | None = None,
    include_portfolio_inputs: bool = True,
) -> OrganizationalDecision:
    """Write one typed ``OrganizationalDecision`` and emit ``ceo.decision.created`` (audited).

    ``include_portfolio_inputs`` (FR-043 / T056): the run's ``PortfolioRiskReport`` artefact ids
    are folded into ``supporting_input_artefact_ids`` whenever the objective touched portfolio
    exposure, so a portfolio artefact is never silently left out of a decision it informed.
    """
    inputs = list(supporting_input_artefact_ids or [])
    if include_portfolio_inputs:
        for pid in _portfolio_artefact_ids(session, run.id):
            if pid not in inputs:
                inputs.append(pid)

    row = OrganizationalDecision(
        run_id=run.id,
        decision_type=decision_type.value,
        summary=summary,
        reason=reason,
        supporting_input_artefact_ids=inputs,
        supporting_agents=list(supporting_agents or ["ceo_agent"]),
        next_step=next_step,
        escalated_to_role=escalated_to_role,
        created_at=datetime.now(UTC),
    )
    session.add(row)
    session.flush()
    event_row = events.emit(
        session,
        run_id=run.id,
        event_type="ceo.decision.created",
        subject_type="decision",
        subject_id=row.id,
        # spec 002 US6: `reason` alongside `summary`/`next_step` under the uniform key the
        # Activity Stream reads for every event type.
        payload={
            "decision_type": decision_type.value,
            "summary": summary,
            "reason": reason if not next_step else f"{reason} Next: {next_step}",
        },
        audited=True,
    )
    # spec 002 US11 (T050): thread the real AuditLog id this decision's own audited event just
    # created onto its `audit_reference` FK, in the same transaction.
    row.audit_reference = event_row._audit_log_id  # type: ignore[attr-defined]
    return row


def resolve_conflict(
    session: Session, run: OrganizationRun, conflict: Conflict
) -> OrganizationalDecision:
    """Emit ``ceo.conflict_detected`` then record the CEO's ``resolve_conflict`` decision. A
    high-severity conflict is also escalated to a human role (FR-022, SC-014)."""
    events.emit(
        session,
        run_id=run.id,
        event_type="ceo.conflict_detected",
        subject_type="run",
        subject_id=run.id,
        payload={
            "kind": conflict.kind,
            "description": conflict.description,
            "severity": conflict.severity,
            "artefact_ids": conflict.artefact_ids,
            "reason": conflict.description,
        },
        audited=True,
    )
    escalate = conflict.escalate_to_role if conflict.severity == "high" else None
    decision = record_decision(
        session,
        run,
        decision_type=DecisionType.RESOLVE_CONFLICT,
        summary=f"Conflict resolved: {conflict.kind}.",
        reason=conflict.description,
        supporting_input_artefact_ids=conflict.artefact_ids,
        supporting_agents=conflict.supporting_agents or ["ceo_agent"],
        next_step=conflict.next_step,
        escalated_to_role=escalate,
    )
    if escalate is not None:
        record_decision(
            session,
            run,
            decision_type=DecisionType.ESCALATE_HUMAN,
            summary=f"Escalated {conflict.kind} to {escalate}.",
            reason=f"High-severity conflict: {conflict.description}",
            supporting_input_artefact_ids=conflict.artefact_ids,
            supporting_agents=conflict.supporting_agents or ["ceo_agent"],
            escalated_to_role=escalate,
        )
    logger.info(
        "org_conflict_resolved", run_id=str(run.id), kind=conflict.kind, severity=conflict.severity
    )
    return decision


def record_review_request(
    session: Session,
    run: OrganizationRun,
    *,
    reviewer: str,
    subject_artefact_id: str,
    reason: str,
) -> OrganizationalDecision:
    """FR-021: a peer review, requested only where the plan's safety requirements or a risk rule
    ask for one -- recorded as a typed decision, not prompt text."""
    return record_decision(
        session,
        run,
        decision_type=DecisionType.REQUEST_REVIEW,
        summary=f"Peer review requested from {reviewer}.",
        reason=reason,
        supporting_input_artefact_ids=[subject_artefact_id],
        supporting_agents=["ceo_agent", reviewer],
        include_portfolio_inputs=False,
    )


def record_escalation(
    session: Session,
    run: OrganizationRun,
    *,
    to_role: str,
    reason: str,
    supporting_input_artefact_ids: list[str] | None = None,
) -> OrganizationalDecision:
    """FR-022: an escalation to a human governance role."""
    return record_decision(
        session,
        run,
        decision_type=DecisionType.ESCALATE_HUMAN,
        summary=f"Escalated to {to_role}.",
        reason=reason,
        supporting_input_artefact_ids=supporting_input_artefact_ids,
        escalated_to_role=to_role,
        include_portfolio_inputs=False,
    )
