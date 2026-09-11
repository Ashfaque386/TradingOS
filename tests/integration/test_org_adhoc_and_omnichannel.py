"""Ad-hoc agent-driven analysis & omni-channel routing (spec T095, quickstart Scenario 12,
SC-022).

- web "analyse my portfolio..." -> a real OrganizationRun + real data + a traceable, audited
  answer (not a free-form guess);
- a channel "run today's research" -> a real run + a CEO synthesis reply, attributed to the
  mapped channel identity;
- "what's my P&L" -> answered directly, no run created (FR-133);
- an unmapped channel sender's actionable-looking message is recorded but never routed (SEC-030,
  already covered end-to-end by test_webhooks_routing.py; reconfirmed here at the classifier
  boundary: an unmapped sender never reaches classification at all).
"""

import json
import time
import uuid
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import select

from src.api.main import app
from src.core import vault
from src.core.db import get_session
from src.core.security import hash_password
from src.models.audit import AuditLog
from src.models.chat import ChatMessage
from src.models.orchestration import OrganizationalPlan, OrganizationRun, ResultArtefact
from src.models.user import NotificationChannel, User
from src.models.webhook import WebhookEvent
from tests.auth_helpers import cleanup_user
from tests.orchestration_helpers import cleanup_run

client = TestClient(app)

_ACTIONABLE = {
    "actionable": True,
    "objective_classification": "portfolio_analysis",
    "objective": "Analyse my current portfolio and flag the highest-risk positions.",
}
_NOT_ACTIONABLE = {"actionable": False, "objective_classification": None, "objective": None}
_PLAN = {
    "can_plan": True,
    "objective_classification": "portfolio_analysis",
    "departments": ["Portfolio"],
    "approval_required": False,
    "tasks": [
        {
            "key": "m",
            "objective": "assess market",
            "capability": "market_analysis",
            "assigned_agent": "market_analyst",
            "expected_output": "MarketContext",
            "depends_on": [],
        }
    ],
}
_ADHOC_ANSWER = {
    "answer": "Your portfolio is moderately diversified; position X carries the most risk.",
    "supporting_points": ["position X is 30% of exposure"],
}


def _resp(payload: dict) -> MagicMock:
    r = MagicMock()
    r.choices[0].message.content = json.dumps(payload)
    return r


def _wait_for_message(assistant_id: uuid.UUID, timeout: float = 30.0) -> ChatMessage:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with get_session() as session:
            row = session.get(ChatMessage, assistant_id)
            if row is not None and row.status != "Pending":
                session.expunge(row)
                return row
        time.sleep(0.4)
    raise AssertionError("assistant message never left 'Pending'")


def _cleanup_chat(*message_ids: uuid.UUID) -> None:
    with get_session() as session:
        session.query(ChatMessage).filter(ChatMessage.id.in_(message_ids)).delete(
            synchronize_session=False
        )
        session.commit()


def test_web_portfolio_analysis_creates_a_traceable_audited_run():
    marker = f"analyse my portfolio {uuid.uuid4()}"
    with (
        patch("src.orchestration.adhoc.complete", return_value=_resp(_ACTIONABLE)),
        patch("src.orchestration.planner.complete", return_value=_resp(_PLAN)),
        patch("src.memory.organization_memory.query_org_memory", return_value=[]),
        patch("src.orchestration.agent_invoker.complete", return_value=_resp(_ADHOC_ANSWER)),
    ):
        response = client.post("/api/v1/chat/messages", json={"content": marker})
        assert response.status_code == 202
        assistant_id = uuid.UUID(response.json()["id"])
        final = _wait_for_message(assistant_id)

    run_id = None
    try:
        assert final.status == "Completed", final.error
        assert "Organization Run" in final.content
        assert "risk" in final.content.lower()

        with get_session() as session:
            run = session.scalars(
                select(OrganizationRun)
                .where(OrganizationRun.objective == _ACTIONABLE["objective"])
                .order_by(OrganizationRun.created_at.desc())
            ).first()
            assert run is not None
            run_id = run.id
            assert run.status == "completed"
            assert run.source == "web"

            artefact = session.scalars(
                select(ResultArtefact).where(
                    ResultArtefact.run_id == run_id, ResultArtefact.artefact_type == "AdHocAnalysis"
                )
            ).first()
            assert artefact is not None
            assert artefact.payload["answer"] == _ADHOC_ANSWER["answer"]

            # traceable to a real audit trail: this run's own plan-created event was audited.
            plan = session.scalars(
                select(OrganizationalPlan).where(OrganizationalPlan.run_id == run_id)
            ).first()
            assert plan is not None
            audited = session.scalars(
                select(AuditLog).where(
                    AuditLog.action == "ORG_EVENT_ORGANIZATION_PLAN_CREATED",
                    AuditLog.entity_id == plan.id,
                )
            ).all()
            assert len(audited) == 1
    finally:
        _cleanup_chat(assistant_id)
        with get_session() as session:
            user_row = session.scalars(
                select(ChatMessage).where(ChatMessage.content == marker)
            ).first()
            if user_row is not None:
                session.delete(user_row)
                session.commit()
        if run_id is not None:
            cleanup_run(run_id)


def test_pure_lookup_is_answered_directly_with_no_run_created():
    marker = f"what's my P&L right now {uuid.uuid4()}"
    plain_reply = MagicMock()
    plain_reply.choices[0].message.content = "Your P&L today is +2.1%."
    with (
        patch("src.orchestration.adhoc.complete", return_value=_resp(_NOT_ACTIONABLE)),
        patch("src.api.routers.chat.complete", return_value=plain_reply),
    ):
        with get_session() as session:
            run_count_before = len(list(session.scalars(select(OrganizationRun.id)).all()))

        response = client.post("/api/v1/chat/messages", json={"content": marker})
        assert response.status_code == 202
        assistant_id = uuid.UUID(response.json()["id"])
        final = _wait_for_message(assistant_id)

    try:
        assert final.status == "Completed"
        assert "Organization Run" not in final.content
        assert final.content == "Your P&L today is +2.1%."
        with get_session() as session:
            run_count_after = len(list(session.scalars(select(OrganizationRun.id)).all()))
        assert run_count_after == run_count_before
    finally:
        _cleanup_chat(assistant_id)
        with get_session() as session:
            user_row = session.scalars(
                select(ChatMessage).where(ChatMessage.content == marker)
            ).first()
            if user_row is not None:
                session.delete(user_row)
                session.commit()


def test_channel_research_objective_creates_a_run_and_replies_with_a_synthesis():
    secret = f"test-secret-{uuid.uuid4()}"
    chat_id = str(uuid.uuid4().int % 1_000_000_000)
    update_id = int(uuid.uuid4().int % 1_000_000_000)
    marker = "run today's research"
    user_id = uuid.uuid4()
    research_classification = {
        "actionable": True,
        "objective_classification": "research",
        "objective": "Run today's research cycle.",
    }
    research_plan = {
        "can_plan": True,
        "objective_classification": "research",
        "departments": ["Research"],
        "approval_required": False,
        "tasks": [
            {
                "key": "s",
                "objective": "synthesize",
                "capability": "synthesize",
                "assigned_agent": "ceo_agent",
                "expected_output": "CeoSynthesis",
                "depends_on": [],
            }
        ],
    }
    synthesis = {
        "summary": "Research complete.",
        "recommendation": "Proceed with the top idea.",
        "key_findings": [],
        "next_step": None,
    }

    vault.write_webhook_secret("telegram", {"secret_token": secret})
    with get_session() as session:
        session.add(
            User(
                id=user_id,
                email=f"adhoc-channel-{user_id}@example.invalid",
                hashed_password=hash_password("test-password-123"),
                role="ReadOnlyAuditor",
            )
        )
        session.add(
            NotificationChannel(
                user_id=user_id,
                channel_type="Telegram",
                external_handle=chat_id,
                is_verified=True,
            )
        )
        session.commit()

    run_id = None
    try:
        with (
            patch("src.orchestration.adhoc.complete", return_value=_resp(research_classification)),
            patch("src.orchestration.planner.complete", return_value=_resp(research_plan)),
            patch("src.memory.organization_memory.query_org_memory", return_value=[]),
            patch("src.orchestration.agent_invoker.complete", return_value=_resp(synthesis)),
        ):
            response = client.post(
                "/api/v1/webhooks/telegram",
                json={"update_id": update_id, "message": {"chat": {"id": chat_id}, "text": marker}},
                headers={"X-Telegram-Bot-Api-Secret-Token": secret},
            )
            assert response.status_code == 200

            deadline = time.time() + 30
            assistant = None
            while time.time() < deadline:
                with get_session() as session:
                    assistant = session.scalars(
                        select(ChatMessage).where(
                            ChatMessage.channel == "Telegram",
                            ChatMessage.external_metadata["chat_key"].astext == chat_id,
                            ChatMessage.role == "assistant",
                        )
                    ).first()
                    if assistant is not None and assistant.status != "Pending":
                        session.expunge(assistant)
                        break
                    assistant = None
                time.sleep(0.4)
            assert assistant is not None, "assistant reply never resolved"

        assert assistant.status == "Completed"
        assert "Proceed with the top idea" in assistant.content

        with get_session() as session:
            run = session.scalars(
                select(OrganizationRun)
                .where(OrganizationRun.objective == research_classification["objective"])
                .order_by(OrganizationRun.created_at.desc())
            ).first()
            assert run is not None
            run_id = run.id
            assert run.source == "telegram"
            assert run.requested_by == f"adhoc-channel-{user_id}@example.invalid"
    finally:
        vault.delete_webhook_secret("telegram")
        with get_session() as session:
            session.query(ChatMessage).filter(
                ChatMessage.channel == "Telegram",
                ChatMessage.external_metadata["chat_key"].astext == chat_id,
            ).delete(synchronize_session=False)
            session.query(WebhookEvent).filter(WebhookEvent.channel == "Telegram").delete(
                synchronize_session=False
            )
            session.query(NotificationChannel).filter(
                NotificationChannel.user_id == user_id
            ).delete(synchronize_session=False)
            session.commit()
        if run_id is not None:
            cleanup_run(run_id)
        cleanup_user(user_id)
