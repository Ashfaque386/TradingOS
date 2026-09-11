"""Attention queue + decision-resolve API (spec T069 backend deps, contracts/rest-api.md
§attention). Extends US2's organisation router with the two endpoints US5's console needs.
"""

from fastapi.testclient import TestClient

from src.api.main import app
from src.core.db import get_session
from src.core.security import (
    ROLE_PORTFOLIO_MANAGER,
    ROLE_READ_ONLY_AUDITOR,
    ROLE_RISK_MANAGER,
)
from src.models.orchestration import OrganizationalDecision
from src.orchestration import decisions
from src.orchestration.enums import DecisionType
from tests.auth_helpers import auth_header, cleanup_user, create_authenticated_user
from tests.orchestration_helpers import cleanup_run, seed_run_with_tasks

client = TestClient(app)


def _reader() -> tuple[object, dict[str, str]]:
    uid, token = create_authenticated_user(ROLE_RISK_MANAGER)
    return uid, auth_header(token)


def test_run_detail_carries_task_counts_and_pending_approvals():
    run_id, _ = seed_run_with_tasks(
        [
            {"key": "a", "capability": "market_analysis", "assigned_agent": "market_analyst"},
            {"key": "b", "capability": "news_ingestion", "assigned_agent": "news_agent"},
        ]
    )
    uid, headers = _reader()
    try:
        r = client.get(f"/api/v1/organization/runs/{run_id}", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert body["task_counts"].get("planned") == 2
        assert body["pending_approvals"] == 0
        assert "result_summary" in body and "ended_at" in body
    finally:
        cleanup_user(uid)
        cleanup_run(run_id)


def test_attention_lists_blocked_tasks_and_escalated_decisions():
    run_id, _keys = seed_run_with_tasks(
        [{"key": "a", "capability": "market_analysis", "assigned_agent": "market_analyst"}]
    )
    uid, headers = _reader()
    decision_id = None
    try:
        with get_session() as session:
            from src.models.orchestration import OrganizationRun

            run = session.get(OrganizationRun, run_id)
            d = decisions.record_decision(
                session,
                run,
                decision_type=DecisionType.ESCALATE_HUMAN,
                summary="Escalated a conflict.",
                reason="market vs sentiment",
                escalated_to_role="RiskManager",
            )
            session.commit()
            decision_id = d.id

        r = client.get("/api/v1/organization/attention", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert any(dd["decision_id"] == str(decision_id) for dd in body["escalated_decisions"])
        assert "pending_approvals" in body and "stalled_runs" in body
    finally:
        cleanup_user(uid)
        cleanup_run(run_id)
        if decision_id is not None:
            with get_session() as session:
                session.query(OrganizationalDecision).filter(
                    OrganizationalDecision.id == decision_id
                ).delete()
                session.commit()


def test_resolve_decision_rbac_and_idempotency():
    run_id, _ = seed_run_with_tasks(
        [{"key": "a", "capability": "market_analysis", "assigned_agent": "market_analyst"}]
    )
    ro_id, ro_token = create_authenticated_user(ROLE_READ_ONLY_AUDITOR)
    pm_id, pm_token = create_authenticated_user(ROLE_PORTFOLIO_MANAGER)
    decision_id = None
    try:
        with get_session() as session:
            from src.models.orchestration import OrganizationRun

            run = session.get(OrganizationRun, run_id)
            d = decisions.record_decision(
                session,
                run,
                decision_type=DecisionType.RESOLVE_CONFLICT,
                summary="Conflict.",
                reason="opposing signals",
                escalated_to_role="RiskManager",
            )
            session.commit()
            decision_id = d.id

        denied = client.post(
            f"/api/v1/organization/decisions/{decision_id}/resolve",
            json={"note": "looks fine"},
            headers=auth_header(ro_token),
        )
        assert denied.status_code == 403

        ok = client.post(
            f"/api/v1/organization/decisions/{decision_id}/resolve",
            json={"note": "reviewed the evidence; proceed with reduced size"},
            headers=auth_header(pm_token),
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["resolved_by"]

        again = client.post(
            f"/api/v1/organization/decisions/{decision_id}/resolve",
            json={"note": "again"},
            headers=auth_header(pm_token),
        )
        assert again.status_code == 409
    finally:
        cleanup_user(ro_id)
        cleanup_user(pm_id)
        cleanup_run(run_id)
        if decision_id is not None:
            with get_session() as session:
                session.query(OrganizationalDecision).filter(
                    OrganizationalDecision.id == decision_id
                ).delete()
                session.commit()


def test_run_detail_and_attention_surface_dataset_freshness():
    """T088: staleness is visible at both the run level and the cross-run attention queue."""
    run_id, _keys = seed_run_with_tasks(
        [
            {
                "key": "a",
                "capability": "market_analysis",
                "assigned_agent": "market_analyst",
                "required_datasets": ["ohlcv_daily"],
            }
        ]
    )
    uid, headers = _reader()
    try:
        r = client.get(f"/api/v1/organization/runs/{run_id}", headers=headers)
        assert r.status_code == 200
        assert "ohlcv_daily" in r.json()["dataset_freshness"]

        a = client.get("/api/v1/organization/attention", headers=headers)
        assert a.status_code == 200
        assert "stale_datasets" in a.json()

        f = client.get("/api/v1/organization/freshness", headers=headers)
        assert f.status_code == 200
        assert any(d["dataset_name"] == "ohlcv_daily" for d in f.json())
    finally:
        cleanup_user(uid)
        cleanup_run(run_id)
