"""(Provider-failure -- MANDATORY) Integration test (spec T105, brief §84, quickstart Scenario
10, SC-018): a configured provider fails -> the real fallback chain routes around it, the run
still succeeds, the persisted artefact's `provenance.provider_used` names the provider that
*actually* served the call (never a generic "orchestration-chain" label), a real, audited
`agent.fallback` event is recorded, and `GET /providers/health` reports the failed provider
`unreachable` from this real failed attempt -- not a fabricated probe.
"""

from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select

from src.agents import llm_router
from src.api.main import app
from src.core.db import get_session
from src.core.security import ROLE_SYSTEM_ADMINISTRATOR
from src.models.orchestration import OrganizationalEvent, ResultArtefact, Task
from src.orchestration import task_engine
from src.orchestration.enums import TaskStatus
from tests.auth_helpers import auth_header, cleanup_user, create_authenticated_user
from tests.orchestration_helpers import cleanup_run, seed_run_with_tasks

client = TestClient(app)

_SYNTHESIS_JSON = (
    '{"summary": "ok", "recommendation": "hold", "key_findings": [], "next_step": null}'
)


def _fake_response(content: str) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def _fail_every_provider_but_ollama(**kwargs: object) -> SimpleNamespace:
    """A real chain always has `ollama` as the guaranteed, no-key-needed last resort (routing.yaml
    -- see its own header comment) -- failing everything else deterministically exercises a real
    fallback-to-ollama regardless of which cloud provider keys happen to be configured in
    whatever environment this test runs in."""
    model = kwargs["model"]
    assert isinstance(model, str)
    if model.startswith("ollama/"):
        return _fake_response(_SYNTHESIS_JSON)
    raise RuntimeError(f"simulated outage for {model}")


def test_a_failed_provider_falls_back_and_reports_real_provenance_and_health():
    admin_id, _token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    run_id, keys = seed_run_with_tasks(
        [{"key": "synth", "capability": "synthesize", "assigned_agent": "ceo_agent"}]
    )
    try:
        with get_session() as session:
            session.query(Task).filter(Task.id == keys["synth"]).update(
                {Task.status: TaskStatus.READY.value}
            )
            session.commit()
        with patch(
            "src.agents.llm_router.litellm.completion",
            side_effect=_fail_every_provider_but_ollama,
        ):
            task_engine._execute_task(run_id, keys["synth"])

        with get_session() as session:
            artefact = session.scalar(
                select(ResultArtefact).where(ResultArtefact.task_id == keys["synth"])
            )
            assert artefact is not None
            assert artefact.provenance["provider_used"] == "ollama"

            events = session.scalars(
                select(OrganizationalEvent).where(
                    OrganizationalEvent.run_id == run_id,
                    OrganizationalEvent.event_type == "agent.fallback",
                )
            ).all()
            assert len(events) == 1
            assert events[0].payload["provider_used"] == "ollama"
            assert events[0].payload["failed_providers"]  # at least one real failed attempt named

        # GET /providers/health: the real failed provider(s) this test just made fail show
        # unreachable -- read from llm_router's own real, process-local failure tracker (the
        # exact state this endpoint serves), not re-derived independently.
        real_failures = llm_router.get_provider_failure_status()
        assert real_failures  # at least one provider genuinely recorded a failure just now

        response = client.get("/api/v1/providers/health", headers=auth_header(_token))
        assert response.status_code == 200
        health_by_provider = {row["provider"]: row for row in response.json()}
        for failed_provider in real_failures:
            assert health_by_provider[failed_provider]["availability"] == "unreachable"
            assert health_by_provider[failed_provider]["last_failure_at"] is not None
    finally:
        cleanup_run(run_id)
        cleanup_user(admin_id)


def test_total_outage_produces_an_honest_degraded_artefact_never_a_fabricated_one():
    """`_synthesize_handler` catches `NoProviderAvailableError` and produces an honest degraded
    `CeoSynthesis` (a synthesis can genuinely say "nothing came back") rather than raising --
    that degraded path must itself stay honest: no `provider_used` claimed, and the summary
    says so, never a fabricated success."""
    admin_id, _token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    run_id, keys = seed_run_with_tasks(
        [{"key": "synth", "capability": "synthesize", "assigned_agent": "ceo_agent"}]
    )
    try:
        with get_session() as session:
            session.query(Task).filter(Task.id == keys["synth"]).update(
                {Task.status: TaskStatus.READY.value}
            )
            session.commit()
        with patch(
            "src.agents.llm_router.litellm.completion",
            side_effect=RuntimeError("simulated total outage"),
        ):
            task_engine._execute_task(run_id, keys["synth"])

        with get_session() as session:
            artefact = session.scalar(
                select(ResultArtefact).where(ResultArtefact.task_id == keys["synth"])
            )
            assert artefact is not None
            assert artefact.provenance["provider_used"] is None
            assert "unavailable" in artefact.payload["summary"].lower()
            task = session.get(Task, keys["synth"])
            assert task is not None
            assert task.status == TaskStatus.COMPLETED.value  # honest degraded output, not a lie
    finally:
        cleanup_run(run_id)
        cleanup_user(admin_id)
