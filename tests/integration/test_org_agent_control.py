"""Enforced agent enable/disable across all agents (spec T099, quickstart Scenario 11,
SC-013).

- disabling the sole agent for a required capability -> the CEO records a real escalation
  decision, the task itself reaches a real, distinct `ESCALATED` status (spec 002 US7/C-5 --
  this exact branch previously collapsed into the generic `BLOCKED` status, indistinguishable
  from a task blocked only because a dependency never satisfied; the escalated task's own
  *dependents* still become `BLOCKED` via `mark_unsatisfiable`, which is the distinction US7
  makes observable), never dispatches the disabled agent, and independent tasks are unaffected;
- re-enabling it -> a freshly-dispatched task using that capability succeeds again;
- when an *enabled* fallback agent exists for the same capability, the CEO reassigns to it
  instead of blocking (unit-level: no two real agents share a capability today, so the fallback
  lookup is patched to prove this branch of the real policy code);
- disabling the Audit Agent is refused (Business Rule 5) -- already covered end-to-end by
  test_agent_control_api.py::test_audit_agent_cannot_be_disabled; reconfirmed here at the
  service layer the task engine itself relies on.
"""

from unittest.mock import patch

import pytest
from sqlalchemy import select

from src.agents.control import AUDIT_AGENT_NAME, is_agent_enabled, set_agent_enabled
from src.core.db import get_session
from src.core.security import ROLE_SYSTEM_ADMINISTRATOR
from src.models.agent import AgentControlState
from src.models.orchestration import OrganizationalDecision, OrganizationalEvent, Task
from src.orchestration import task_engine
from src.orchestration.enums import TaskStatus
from tests.auth_helpers import cleanup_user, create_authenticated_user
from tests.orchestration_helpers import cleanup_run, seed_run_with_tasks


def _cleanup_control_row(agent_name: str) -> None:
    with get_session() as session:
        session.query(AgentControlState).filter(AgentControlState.agent_name == agent_name).delete()
        session.commit()


def test_disabling_the_sole_agent_escalates_the_task_and_records_an_escalation() -> None:
    admin_id, _token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    run_id, keys = seed_run_with_tasks(
        [
            {
                "key": "indep",
                "capability": "sentiment_analysis",
                "assigned_agent": "sentiment_agent",
            },
            {
                "key": "needs_agent",
                "capability": "market_analysis",
                "assigned_agent": "market_analyst",
            },
        ]
    )
    try:
        with get_session() as session:
            set_agent_enabled(
                session,
                agent_name="market_analyst",
                enabled=False,
                reason="US9 test: taken offline for maintenance",
                updated_by_user_id=admin_id,
            )
            session.commit()
            assert is_agent_enabled(session, "market_analyst") is False

        task_engine.run_scheduler_loop(run_id)

        with get_session() as session:
            tasks = {
                t.capability: t
                for t in session.scalars(select(Task).where(Task.run_id == run_id)).all()
            }
            # Independent work is unaffected by the disabled agent.
            assert tasks["sentiment_analysis"].status == TaskStatus.COMPLETED.value
            escalated = tasks["market_analysis"]
            assert escalated.status == TaskStatus.ESCALATED.value
            assert "agent unavailable" in (escalated.blocked_reason or "")
            assert escalated.result_artefact_id is None

            decisions = session.scalars(
                select(OrganizationalDecision).where(
                    OrganizationalDecision.run_id == run_id,
                    OrganizationalDecision.decision_type == "escalate_human",
                )
            ).all()
            assert len(decisions) == 1
            assert decisions[0].escalated_to_role == "SystemAdministrator"

            events = session.scalars(
                select(OrganizationalEvent).where(OrganizationalEvent.run_id == run_id)
            ).all()
            assert any(
                e.event_type == "task.escalated" and e.payload.get("agent") == "market_analyst"
                for e in events
            )
    finally:
        cleanup_run(run_id)
        _cleanup_control_row("market_analyst")
        cleanup_user(admin_id)


def test_re_enabling_lets_a_fresh_dispatch_of_that_capability_succeed() -> None:
    admin_id, _token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    with get_session() as session:
        set_agent_enabled(
            session,
            agent_name="market_analyst",
            enabled=False,
            reason="US9 test",
            updated_by_user_id=admin_id,
        )
        session.commit()

    with get_session() as session:
        set_agent_enabled(
            session,
            agent_name="market_analyst",
            enabled=True,
            reason=None,
            updated_by_user_id=admin_id,
        )
        session.commit()
        assert is_agent_enabled(session, "market_analyst") is True

    run_id, keys = seed_run_with_tasks(
        [{"key": "a", "capability": "market_analysis", "assigned_agent": "market_analyst"}]
    )
    try:
        task_engine.run_scheduler_loop(run_id)
        with get_session() as session:
            task = session.get(Task, keys["a"])
            assert task is not None
            assert task.status == TaskStatus.COMPLETED.value
            assert task.result_artefact_id is not None
    finally:
        cleanup_run(run_id)
        _cleanup_control_row("market_analyst")
        cleanup_user(admin_id)


def test_when_a_fallback_agent_exists_the_ceo_reassigns_instead_of_blocking() -> None:
    """No two real agents currently declare the same capability -- `find_by_capability` is
    patched here to exercise the real `reassign` branch of the same policy code the previous
    test exercised the `escalate` branch of."""
    admin_id, _token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    run_id, keys = seed_run_with_tasks(
        [{"key": "a", "capability": "market_analysis", "assigned_agent": "market_analyst"}]
    )
    try:
        with get_session() as session:
            set_agent_enabled(
                session,
                agent_name="market_analyst",
                enabled=False,
                reason="US9 test: force a fallback",
                updated_by_user_id=admin_id,
            )
            # _execute_task claims via `WHERE status='ready'` -- seed_run_with_tasks leaves new
            # tasks `planned` (dependency_resolver.ready_tasks is what promotes that in the real
            # scheduler loop); called directly here, so promote it by hand first.
            session.query(Task).filter(Task.id == keys["a"]).update(
                {Task.status: TaskStatus.READY.value}
            )
            session.commit()

        with patch(
            "src.orchestration.capability_registry.find_by_capability",
            return_value=["sentiment_agent"],
        ):
            task_engine._execute_task(run_id, keys["a"])

        with get_session() as session:
            task = session.get(Task, keys["a"])
            assert task is not None
            assert task.assigned_agent == "sentiment_agent"
            assert task.status == TaskStatus.READY.value

            reassign = session.scalars(
                select(OrganizationalDecision).where(
                    OrganizationalDecision.run_id == run_id,
                    OrganizationalDecision.decision_type == "reassign",
                )
            ).first()
            assert reassign is not None
            assert "market_analyst" in reassign.summary and "sentiment_agent" in reassign.summary

            events = session.scalars(
                select(OrganizationalEvent).where(
                    OrganizationalEvent.run_id == run_id,
                    OrganizationalEvent.event_type == "task.reassigned",
                )
            ).all()
            assert len(events) == 1
            assert events[0].payload["to_agent"] == "sentiment_agent"
    finally:
        cleanup_run(run_id)
        _cleanup_control_row("market_analyst")
        cleanup_user(admin_id)


def test_audit_agent_cannot_be_disabled_at_the_service_layer() -> None:
    admin_id, _token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        with get_session() as session:
            with pytest.raises(ValueError):
                set_agent_enabled(
                    session,
                    agent_name=AUDIT_AGENT_NAME,
                    enabled=False,
                    reason="an operator trying to turn off the audit trail",
                    updated_by_user_id=admin_id,
                )
            assert is_agent_enabled(session, AUDIT_AGENT_NAME) is True
    finally:
        _cleanup_control_row(AUDIT_AGENT_NAME)
        cleanup_user(admin_id)
