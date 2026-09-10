"""Conflict detection & CEO resolution test (spec T061, FR-022, SC-014).

`detect_conflict` is a deterministic comparator over a run's artefacts. When it fires, a
`resolve_conflict` `OrganizationalDecision` -- with a rationale and the conflicting artefact ids
as supporting inputs -- must be recorded before the run proceeds; a high-severity conflict also
records a human escalation.
"""

from sqlalchemy import select

from src.core.db import get_session
from src.models.orchestration import OrganizationalDecision, OrganizationalEvent, OrganizationRun
from src.orchestration import artefact_store, decisions
from src.orchestration.enums import ArtefactDisposition
from tests.orchestration_helpers import cleanup_run, seed_run_with_tasks

_MARKET_BULLISH = {
    "market_regime": "Bullish",
    "sector_rankings": ["IT", "Banking"],
    "volatility_assessment": "low",
    "macro_outlook": "constructive",
    "confidence_score": 0.7,
    "insights": ["breadth improving"],
}
_SENTIMENT_NEGATIVE = {"per_symbol": {"AAA": -0.6, "BBB": -0.55}, "per_sector": {"IT": -0.4}}


def _persist(run_id, task_id, artefact_type, payload):
    with get_session() as session:
        prov = artefact_store.build_provenance(
            agent="test", task_id=task_id, run_id=run_id, inputs=[]
        )
        art = artefact_store.persist_artefact(
            session,
            run_id=run_id,
            task_id=task_id,
            artefact_type=artefact_type,
            payload=payload,
            provenance=prov,
            disposition=ArtefactDisposition.INFORMATIONAL,
        )
        session.commit()
        return str(art.id)


def test_opposing_market_and_sentiment_force_a_recorded_resolution():
    run_id, keys = seed_run_with_tasks(
        [
            {"key": "m", "capability": "market_analysis", "assigned_agent": "market_analyst"},
            {"key": "s", "capability": "sentiment_analysis", "assigned_agent": "sentiment_agent"},
        ]
    )
    try:
        m_id = _persist(run_id, keys["m"], "MarketContext", _MARKET_BULLISH)
        s_id = _persist(run_id, keys["s"], "SentimentReport", _SENTIMENT_NEGATIVE)

        with get_session() as session:
            from src.models.orchestration import ResultArtefact

            arts = list(
                session.scalars(select(ResultArtefact).where(ResultArtefact.run_id == run_id)).all()
            )
            conflict = decisions.detect_conflict(arts)
            assert conflict is not None
            assert conflict.kind == "market_vs_sentiment"
            assert set(conflict.artefact_ids) == {m_id, s_id}

            run = session.get(OrganizationRun, run_id)
            decision = decisions.resolve_conflict(session, run, conflict)
            session.commit()

        with get_session() as session:
            rows = session.scalars(
                select(OrganizationalDecision).where(
                    OrganizationalDecision.run_id == run_id,
                    OrganizationalDecision.decision_type == "resolve_conflict",
                )
            ).all()
            assert len(rows) == 1
            d = rows[0]
            assert d.reason  # a rationale, not empty
            assert set(d.supporting_input_artefact_ids) >= {m_id, s_id}
            assert d.next_step

            events = {
                e.event_type
                for e in session.scalars(
                    select(OrganizationalEvent).where(OrganizationalEvent.run_id == run_id)
                ).all()
            }
            assert "ceo.conflict_detected" in events
            assert "ceo.decision.created" in events
        assert decision.decision_type == "resolve_conflict"
    finally:
        cleanup_run(run_id)


def test_high_severity_conflict_also_escalates_to_a_human_role():
    run_id, keys = seed_run_with_tasks(
        [{"key": "m", "capability": "market_analysis", "assigned_agent": "market_analyst"}]
    )
    try:
        a_id = _persist(run_id, keys["m"], "MarketContext", _MARKET_BULLISH)
        conflict = decisions.Conflict(
            kind="compliance_vs_proposal",
            description="Compliance 'Block' against a strategy that means to proceed.",
            artefact_ids=[a_id],
            severity="high",
            escalate_to_role="RiskManager",
            next_step="Do not proceed.",
        )
        with get_session() as session:
            run = session.get(OrganizationRun, run_id)
            decisions.resolve_conflict(session, run, conflict)
            session.commit()

        with get_session() as session:
            rows = session.scalars(
                select(OrganizationalDecision).where(OrganizationalDecision.run_id == run_id)
            ).all()
            types = {r.decision_type for r in rows}
            assert "resolve_conflict" in types
            assert "escalate_human" in types
            assert any(r.escalated_to_role == "RiskManager" for r in rows)
    finally:
        cleanup_run(run_id)
