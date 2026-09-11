"""Ad-hoc agent-driven analysis & omni-channel routing (spec T092/T093, FR-130..133).

An inbound chat/channel message is classified: an actionable objective is turned into a real
``OrganizationRun`` (traceable execution, real data, an audited artefact); a pure data lookup is
answered directly by the existing chat reply pipeline, with no run created (FR-133) -- chat must
never present a free-form guess as if the organisation had actually done the work, and must never
burn a real run on a greeting.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from typing import Literal

import structlog
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from src.agents.llm_router import complete
from src.agents.nodes.common import extract_json
from src.agents.prompt_registry import get_active_prompt
from src.core.db import get_session
from src.models.chat import ChatMessage
from src.models.orchestration import OrganizationalDecision, OrganizationRun, ResultArtefact
from src.orchestration import run_manager
from src.orchestration.enums import RunSource, RunStatus

logger = structlog.get_logger(__name__)

CLASSIFIER_PROMPT_SLUG = "adhoc_classifier"

AdHocObjectiveKind = Literal[
    "portfolio_analysis",
    "risk_ranking",
    "drawdown_explanation",
    "strategy_failure_explanation",
    "rerun_decision",
    "research",
    "general",
]

ADHOC_OBJECTIVE_KINDS: frozenset[str] = frozenset(
    {
        "portfolio_analysis",
        "risk_ranking",
        "drawdown_explanation",
        "strategy_failure_explanation",
        "rerun_decision",
    }
)

_TERMINAL_RUN_STATUSES = (
    RunStatus.COMPLETED.value,
    RunStatus.FAILED.value,
    RunStatus.CANNOT_PLAN.value,
    RunStatus.CANCELLED.value,
)
_RUN_WATCH_TIMEOUT_SECONDS = 180.0


class _Classification(BaseModel):
    model_config = ConfigDict(extra="ignore")

    actionable: bool = False
    objective_classification: AdHocObjectiveKind | None = None
    objective: str | None = None


def classify_message(text: str) -> _Classification:
    """A real LLM classification call. Defaults to ``actionable=False`` on any failure -- a
    classifier hiccup must degrade to "answer directly", never to a fabricated organisation run."""
    try:
        system_prompt = get_active_prompt(CLASSIFIER_PROMPT_SLUG)
        response = complete(
            "orchestration",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
        )
        raw = extract_json(response.choices[0].message.content)
        return _Classification.model_validate_json(raw)
    except (
        Exception
    ) as exc:  # noqa: BLE001 -- any classifier hiccup -> answer directly, never a run
        logger.warning("adhoc_classification_fallback", error=str(exc))
        return _Classification(actionable=False)


def maybe_route_to_organization(
    *, text: str, channel: str, requested_by: str | None
) -> uuid.UUID | None:
    """FR-130/132/133: classify ``text``; if actionable, create a real ``OrganizationRun`` and
    return its id. Returns ``None`` for a pure lookup -- the caller answers it directly, no run
    created."""
    classification = classify_message(text)
    if not classification.actionable or not classification.objective:
        return None
    try:
        source = RunSource(channel.lower())
    except ValueError:
        source = RunSource.API
    with get_session() as session:
        run = run_manager.create_run(
            session,
            objective=classification.objective,
            source=source,
            requested_by=requested_by,
        )
        run_id = run.id
    logger.info(
        "adhoc_objective_routed_to_organization",
        run_id=str(run_id),
        channel=channel,
        objective_classification=classification.objective_classification,
    )
    return run_id


def _compose_reply(run_id: uuid.UUID, status: str | None) -> tuple[str, str]:
    """Returns ``(reply_text, chat_message_status)``."""
    with get_session() as session:
        run = session.get(OrganizationRun, run_id)
        if run is None:
            return "The organisation run for this request could not be found.", "Failed"
        if status == RunStatus.COMPLETED.value:
            synthesis = session.scalars(
                select(ResultArtefact)
                .where(
                    ResultArtefact.run_id == run_id,
                    ResultArtefact.artefact_type.in_(("CeoSynthesis", "AdHocAnalysis")),
                )
                .order_by(ResultArtefact.created_at.desc())
            ).first()
            if synthesis is None:
                return (
                    f"[Organization Run {run_id}] Completed, but produced no synthesis artefact.",
                    "Completed",
                )
            payload = synthesis.payload
            if synthesis.artefact_type == "AdHocAnalysis":
                body = str(payload.get("answer", ""))
            else:
                summary = payload.get("summary", "")
                recommendation = payload.get("recommendation", "")
                body = (
                    f"{summary}\n\nRecommendation: {recommendation}"
                    if recommendation
                    else str(summary)
                )
            return f"[Organization Run {run_id}]\n{body}", "Completed"
        if status == RunStatus.CANNOT_PLAN.value:
            decision = session.scalars(
                select(OrganizationalDecision)
                .where(
                    OrganizationalDecision.run_id == run_id,
                    OrganizationalDecision.decision_type == "cannot_plan",
                )
                .order_by(OrganizationalDecision.created_at.desc())
            ).first()
            reason = decision.reason if decision is not None else "the objective is unservable"
            return f"The organisation could not plan this objective: {reason}", "Failed"
        if status in (RunStatus.FAILED.value, RunStatus.CANCELLED.value):
            return (
                f"[Organization Run {run_id}] ended '{status}' -- see the console for details.",
                "Failed",
            )
        return (
            f"[Organization Run {run_id}] is still running; check the Command Center for "
            "live progress.",
            "Completed",
        )


def watch_run_and_reply(
    *,
    assistant_message_id: uuid.UUID,
    run_id: uuid.UUID,
    on_complete: Callable[[str, str], None] | None = None,
) -> None:
    """Polls ``run_id`` to a terminal state (or a timeout) and resolves the pending assistant
    ``ChatMessage`` with the run's real synthesis -- run in a background thread, mirroring
    ``chat.py::generate_and_store_reply``'s own pending-row-resolution contract."""
    deadline = time.time() + _RUN_WATCH_TIMEOUT_SECONDS
    status: str | None = None
    while time.time() < deadline:
        with get_session() as session:
            run = session.get(OrganizationRun, run_id)
            status = run.status if run is not None else None
        if status in _TERMINAL_RUN_STATUSES:
            break
        time.sleep(1.0)

    reply, chat_status = _compose_reply(run_id, status)
    with get_session() as session:
        message = session.get(ChatMessage, assistant_message_id)
        if message is not None:
            message.content = reply
            message.status = chat_status
            session.commit()
    if on_complete is not None:
        on_complete(reply, chat_status)


def classify_and_dispatch(
    *,
    assistant_message_id: uuid.UUID,
    text: str,
    channel: str,
    requested_by: str | None,
    history: list[tuple[str, str, str]] | None = None,
    on_complete: Callable[[str, str], None] | None = None,
) -> None:
    """Background-thread entry point (US8). Classifies ``text``; an actionable objective is
    routed to a real ``OrganizationRun`` and its synthesis awaited, a pure lookup falls through
    to the existing direct chat-reply pipeline. **Never** call this on a request-handling
    thread -- the classifier is a real LLM call, and a webhook must ack fast (Discord's own
    3-second deadline in particular); the caller must dispatch it via a background thread (see
    ``start_classify_and_dispatch``)."""
    run_id = maybe_route_to_organization(text=text, channel=channel, requested_by=requested_by)
    if run_id is not None:
        watch_run_and_reply(
            assistant_message_id=assistant_message_id, run_id=run_id, on_complete=on_complete
        )
        return

    from src.api.routers.chat import generate_and_store_reply  # deferred: avoids an import cycle

    generate_and_store_reply(
        assistant_message_id=assistant_message_id,
        history=history or [],
        user_content=text,
        on_complete=on_complete,
    )


def start_classify_and_dispatch(
    *,
    assistant_message_id: uuid.UUID,
    text: str,
    channel: str,
    requested_by: str | None,
    history: list[tuple[str, str, str]] | None = None,
    on_complete: Callable[[str, str], None] | None = None,
) -> None:
    threading.Thread(
        target=classify_and_dispatch,
        kwargs={
            "assistant_message_id": assistant_message_id,
            "text": text,
            "channel": channel,
            "requested_by": requested_by,
            "history": history,
            "on_complete": on_complete,
        },
        daemon=True,
    ).start()
