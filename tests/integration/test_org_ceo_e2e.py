"""MANDATORY CEO end-to-end test (spec T044, brief section 79, SC-015/SC-021).

One objective -> CEO plan -> delegated tasks -> independent tasks run concurrently -> dependent
tasks wait -> a synthesis/recommendation is produced -> every major event is persisted + audited.
Uses mocked ``complete`` for both the planner and the CEO synthesis so the whole pipeline runs
without a live LLM.
"""

import json
import time
import uuid
from unittest.mock import MagicMock, patch

from sqlalchemy import select

from src.core.db import get_session
from src.models.audit import AuditLog
from src.models.orchestration import OrganizationalEvent, OrganizationRun, ResultArtefact
from src.orchestration import run_manager
from src.orchestration.enums import RunSource, RunStatus
from tests.orchestration_helpers import cleanup_run

_PLAN = {
    "can_plan": True,
    "objective_classification": "swing_research",
    "departments": ["Market Intelligence", "Executive"],
    "approval_required": True,
    "tasks": [
        {
            "key": "m",
            "objective": "assess market",
            "capability": "market_analysis",
            "assigned_agent": "market_analyst",
            "expected_output": "MarketContext",
            "depends_on": [],
        },
        {
            "key": "n",
            "objective": "ingest news",
            "capability": "news_ingestion",
            "assigned_agent": "news_agent",
            "expected_output": "NewsDigest",
            "depends_on": [],
        },
        {
            "key": "s",
            "objective": "score sentiment",
            "capability": "sentiment_analysis",
            "assigned_agent": "sentiment_agent",
            "expected_output": "SentimentReport",
            "depends_on": ["n"],
        },
        {
            "key": "syn",
            "objective": "synthesise findings",
            "capability": "synthesize",
            "assigned_agent": "ceo_agent",
            "expected_output": "CeoSynthesis",
            "depends_on": ["m", "s"],
        },
    ],
}
_SYNTH = {
    "summary": "Market constructive; low-risk swing setups in IT.",
    "recommendation": "Proceed to strategy generation.",
    "key_findings": ["regime bullish", "sentiment positive"],
    "next_step": "strategy_generation",
}


def _resp(payload: dict) -> MagicMock:
    r = MagicMock()
    r.choices[0].message.content = json.dumps(payload)
    return r


def test_full_ceo_cycle_from_a_single_objective():
    run_id: uuid.UUID | None = None
    try:
        with (
            patch("src.orchestration.planner.complete", return_value=_resp(_PLAN)),
            patch("src.memory.organization_memory.query_org_memory", return_value=[]),
            patch("src.orchestration.agent_invoker.complete", return_value=_resp(_SYNTH)),
        ):
            with get_session() as session:
                run = run_manager.create_run(
                    session,
                    objective="Find low-risk swing opportunities for tomorrow",
                    source=RunSource.API,
                    requested_by="owner@example.invalid",
                )
                run_id = run.id
            deadline = time.time() + 30
            status = None
            while time.time() < deadline:
                with get_session() as s:
                    r = s.get(OrganizationRun, run_id)
                    status = r.status if r else None
                    if status in (
                        RunStatus.COMPLETED.value,
                        RunStatus.FAILED.value,
                        RunStatus.CANNOT_PLAN.value,
                    ):
                        break
                time.sleep(0.4)

        assert status == RunStatus.COMPLETED.value, f"run ended {status}"

        with get_session() as session:
            artefacts = session.scalars(
                select(ResultArtefact).where(ResultArtefact.run_id == run_id)
            ).all()
            by_type = {a.artefact_type for a in artefacts}
            assert "CeoSynthesis" in by_type
            synth = next(a for a in artefacts if a.artefact_type == "CeoSynthesis")
            assert synth.payload["recommendation"] == "Proceed to strategy generation."
            # every artefact is dispositioned (SC-004)
            assert all(a.disposition is not None for a in artefacts)

            events = session.scalars(
                select(OrganizationalEvent).where(OrganizationalEvent.run_id == run_id)
            ).all()
            types = {e.event_type for e in events}
            for expected in {
                "organization.plan.created",
                "organization.run.running",
                "task.started",
                "task.completed",
                "dependency.satisfied",
                "organization.run.completed",
            }:
                assert expected in types, f"missing event {expected}"

            # major events audited
            audit_actions = {
                a.action
                for a in session.scalars(
                    select(AuditLog).where(AuditLog.action.like("ORG_EVENT_%"))
                ).all()
            }
            assert "ORG_EVENT_ORGANIZATION_PLAN_CREATED" in audit_actions
            assert "ORG_EVENT_ORGANIZATION_RUN_COMPLETED" in audit_actions
    finally:
        if run_id is not None:
            cleanup_run(run_id)
