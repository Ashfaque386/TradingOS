# Quickstart — Validation Guide

**Feature**: CEO-Led AI Trading Organization | **Date**: 2026-09-10

This guide lists the runnable scenarios that prove the feature works end-to-end. It maps each spec Success Criterion and the brief's mandatory tests to a concrete check. Implementation lives in `tasks.md` + the codebase; this file is the "how do I know it's done" reference.

All commands run in Docker (constitution II). Prerequisites: `docker compose up -d` (app, app-tls, postgres, qdrant, redis, temporal, vault + unsealer, minio, prometheus, grafana, monte-carlo-worker, tick-publisher, frontend); `docker compose run --rm app alembic upgrade head`; seed data present (`scripts/seed_admin_user.py`, `scripts/seed_paper_account.py`, a fresh EOD ingestion — see Scenario 7); a working LLM provider configured for the `orchestration`/`research`/`coding` chains in `routing.yaml`.

Roles used: `admin@…` = `SystemAdministrator`, `pm@…` = `PortfolioManager`, `rm@…` = `RiskManager`, `ro@…` = `ReadOnlyAuditor`.

---

## Scenario 1 — CEO turns an objective into a dynamic plan (US1 / SC-015, SC-021)

**Steps**
1. `POST /api/v1/organization/runs` as `pm@…` with `{"objective": "Find low-risk swing opportunities for tomorrow"}` → 202 `{run_id, status}`.
2. Poll `GET /organization/runs/{run_id}/plan` until the plan exists.
3. Submit two more, materially different objectives (e.g. "analyse my portfolio's concentration risk", "research a mean-reversion strategy on Bank Nifty").
4. Submit an objective the organisation cannot serve (e.g. "trade crypto perpetuals") .

**Expected**
- Three different plans, each with ≥ 1 task, a per-task `assigned_agent` that exists in `GET /agents`, and an **acyclic** dependency graph referencing only in-plan tasks (data-model §2 validation).
- `organization.plan.created` event and an `AuditLog` entry per plan (contracts/events.md).
- The un-servable objective ends `status="cannot_plan"` with an `OrganizationalDecision(decision_type="cannot_plan", reason=…)` — **no** empty/fabricated plan (FR-008).

**Automated**: `tests/integration/test_org_planner.py` (three objectives → three distinct validated plans; one un-servable → `cannot_plan`).

---

## Scenario 2 — Parallel independent work, dependent work waits (US2 / SC-001, SC-002, SC-015 — **mandatory concurrency test**)

**Steps**
1. Create a run whose plan has ≥ 4 independent tasks (market, news, portfolio-read, data-freshness) and dependent tasks (sentiment depends on news; risk-context depends on portfolio; strategy depends on market+data+sentiment+risk).
2. After completion, read `GET /organization/runs/{run_id}/tasks`.

**Expected**
- The four independent tasks have **overlapping** `[started_at, completed_at]` windows and `ran_concurrently = true`; the independent phase wall-clock ≈ the longest of the four + small overhead (SC-001), **not** their sum.
- `sentiment.started_at ≥ news.completed_at`; `risk_context.started_at ≥ portfolio.completed_at`; `strategy.started_at ≥ max(dependencies.completed_at)` (SC-002).
- `sentiment` shows `status = waiting_for_dependency` with `waiting_for = "NewsDigest"`, `owner_agent = "news_agent"` while news is running; a `dependency.satisfied` event fires when news completes.
- Zero tasks executed with a `required_inputs` entry absent from `received_inputs`.

**Automated**: `tests/integration/test_org_concurrency.py` — **this test is mandatory** (brief §78). Also a claim-race unit test: two workers race the same `ready` task, exactly one runs it (data-model §3 claiming; research R2 watch item).

---

## Scenario 3 — Real human approval gate (US3 / SC-003 — **HITL**)

**Steps**
1. Run a research objective through to a `DeploymentRecommendation` artefact.
2. `GET /organization/approvals?status=pending` → the request exists; `GET /strategies/{id}` → status `PendingPaperApproval`, **not** `PaperTrading`.
3. Wait / verify no scheduled job transitions it (leave it 10 min; re-check).
4. `POST /organization/approvals/{id}/approve` as `rm@…` → **403**, audited denial.
5. `POST …/approve` as `pm@…` → 200; `GET /strategies/{id}` → `PaperTrading`; `approval.approved` event + `AuditLog` (actor, time).
6. In a second run, `POST …/reject` as `admin@…` without `reason` → 422; with `{"reason": "…"}` → 200; strategy → `Deprecated`; never entered `PaperTrading`.
7. Confirm Paper→Live still requires the unchanged `POST /strategies/{id}/promote`.

**Expected**: matches steps. No timeout ever auto-approves (FR-057).

**Automated**: `tests/integration/test_org_approval_gate.py`; `frontend/cypress/e2e/approval_gate.cy.ts` (approvals queue renders; approve moves the card; RO/RM cannot approve).

---

## Scenario 4 — News/Sentiment/Portfolio actually inform research (US4 / SC-004, SC-005)

**Steps**
1. Run a research objective with priority sectors.
2. Read `GET /organization/runs/{run_id}/artefacts`.
3. Re-run with the News source forced unavailable (disable `news_agent` or point its feeds at an unreachable host).

**Expected**
- A `ResearchContext` artefact exists whose `provenance.inputs` reference this run's own `NewsDigest` and `SentimentReport`; the composite research task's `received_inputs` include it (FR-042).
- Every artefact has `disposition ∈ {consumed, informational}` — **zero** `NULL` (SC-004); the run cannot reach `completed` with an undispositioned artefact.
- With News down: the `ResearchContext` has `coverage = "reduced"` listing the missing input; nothing presents partial data as complete (FR-044); sentiment and downstream carry the reduced-confidence marker.
- The portfolio artefact appears in an `OrganizationalDecision.supporting_input_artefact_ids` (FR-043).

**Automated**: `tests/integration/test_org_context_integration.py`.

---

## Scenario 5 — Organization Command Center is live and truthful (US5 / SC-007, SC-008, SC-009)

**Steps**
1. Open `/console` as `pm@…`; start a run.
2. Watch the run workspace (`/console/runs/{runId}`): org task graph, activity stream.
3. Open three agents incl. one non-graph agent (e.g. `news_agent`) via `/console/agents/{agentId}`.
4. Open a completed run's replay.
5. `grep` the built frontend bundle for hard-coded status strings (`"5 real nodes"`, `"running"`, `"approved"` literals not bound to state).
6. Kill and restore the WS connection mid-run.

**Expected**
- Console home summarises CEO status, org health, running/waiting/blocked counts, pending approvals, recent decisions, recent failures, data freshness — all matching `GET /organization/runs/{id}` / `/attention` / `/providers/health` (SC-007), visible within ~2 s of the backend event, no manual refresh.
- Two independent agents render as concurrently active; a dependency edge animates to "active" only when a `dependency.satisfied` event arrives — never simulated (FR-081).
- Each agent's detail view shows the uniform framework (overview, current task, inputs, outputs, tools, skills, model/provider + default-vs-override or "no model — deterministic", activity timeline, dependencies, consumers, previous runs, errors, artefacts, audit refs) populated from real data or an explicit "no data yet" (SC-009).
- A waiting agent states what/why/expected-next (FR-083); a failed agent shows reason/impact/retry/dependents/CEO-response/recommended-action, not just "Failed" (FR-084).
- Replay reconstructs plan → tasks → parallelism → dependencies → hand-offs → results → retries → decisions → approval → outcome from `organizational_events` rows (FR-087); no private reasoning shown.
- Zero hard-coded status strings (SC-008, BUG-G).
- On WS reconnect the console backfills via `?after_sequence=` and resumes without a full reload, keeping the selected run/agent (contracts/websocket.md).

**Automated**: `frontend/cypress/e2e/console_live.cy.ts` (+ a lint/grep check for hard-coded status literals in CI).

---

## Scenario 6 — Agent Settings: prompt versions + provider/model (US6 / SC-010, SC-011, SC-012, SC-016 — **mandatory Agent Settings test**)

**Steps** (for one LLM-backed agent, e.g. `strategy_generator`, as `admin@…`)
1. `/settings/agents/strategy_generator` → view active system prompt + version history.
2. Create a new version → review the diff → confirm it is **inactive**.
3. `PUT /provider-model` `{mode:"CUSTOM", provider:"anthropic", model:"<configured model>"}`; try an invalid model → **422**.
4. `POST /test` with the new version + custom model → returns real `provider/model/latency_ms/structured_output_valid/errors`.
5. Activate the new version; `GET .../config` shows `AuditLog` before/after (SC-012).
6. Trigger a run that uses `strategy_generator`; inspect that task's `task.started` event / `provenance` → `model_used`/`provider_used` = the configured pair (SC-011).
7. For a second agent left on `AUTO`, trigger a run and confirm its provider/model selection equals the pre-feature selection for the same inputs (golden test, SC-010).
8. Open a **deterministic** agent (`python_validator`) → Settings shows "no model — deterministic", no picker (clarify Q5); `PUT /provider-model` on it → 422.
9. Attempt any config change as `pm@…` → **403**, audited (clarify Q4).

**Expected**: matches steps.

**Automated**: `tests/integration/test_agent_settings.py`; `frontend/cypress/e2e/agent_settings.cy.ts`; `tests/unit/test_llm_router_auto_unchanged.py` (golden, SC-010).

---

## Scenario 7 — Data freshness is a first-class fact (US7 / SC-006)

**Steps**
1. Mark `ohlcv_daily` stale (fast-forward the freshness rule, or clear the last-successful timestamp).
2. Submit a research objective that needs it.
3. Observe the plan run.
4. Run the new nightly EOD ingestion job manually (bhavcopy provider); confirm checksum validation.
5. Re-check the previously-blocked tasks.

**Expected**
- The dataset-dependent task is `blocked` with `blocked_reason` containing "data stale"; **independent** tasks (news, portfolio) still run (FR-062).
- `GET /organization/runs/{id}` and the console show per-dataset freshness (last successful update, status); a `dataset.stale` event + Grafana/Slack alert fired.
- No task proceeded on fabricated/interpolated data (FR-063) — assert no synthetic rows were written to the lake on this path.
- After a valid ingestion (checksum ok), `DatasetFreshnessRecord.status = fresh` and the blocked tasks become eligible (`task.ready`).
- A failed/corrupt ingestion does **not** set `fresh` (FR-064).

**Automated**: `tests/integration/test_org_data_freshness.py`; `tests/unit/test_eod_ingestion_checksum.py`.

---

## Scenario 8 — Restart mid-run auto-resumes (SC-023 / FR-019)

**Steps**
1. Start a run; let 2–3 tasks complete; while a later task is running, `docker compose restart app`.
2. After the app is healthy, read the run and its task timeline.

**Expected**
- The run resumes automatically (reaper) from the last completed task; completed tasks are **not** re-executed and their artefacts are **not** regenerated (verifiable: no new `result.created` events for already-done task ids; `created_at` unchanged) (SC-023).
- A task that was mid-execution is re-attempted (retry budget) or marked `failed` with reason — never a false `completed`.
- The composite research sub-graph, if it was mid-flight, resumes via the LangGraph `PostgresSaver` and re-runs only its unfinished nodes.

**Automated**: `tests/integration/test_org_restart_resume.py`.

---

## Scenario 9 — Agent failure handling (SC-017 — **mandatory failure test**)

**Steps**
1. Force one agent's task to fail deterministically (stub the node to raise).
2. Observe the run.

**Expected**
- Task → `failed` after its retry budget; a `task.failed` event; the CEO receives it (`ceo.decision.created` or `task.escalated`); a human is notified on repeated failure (Notification path).
- Downstream dependent tasks do **not** falsely complete — they go `blocked` with a clear reason (FR-017).
- The console shows the true state (agent/task/reason/impact/retry/dependents/CEO-response/recommended-action) (FR-084).
- An `AuditLog` entry exists for the failure.

**Automated**: `tests/integration/test_org_failure_handling.py`.

---

## Scenario 10 — Provider failure transparency (SC-018 — **mandatory provider-failure test**)

**Steps**
1. Configure provider A as unavailable (remove its Vault key / point at an unreachable base URL).
2. Run an objective whose agents would use provider A.

**Expected**
- Routing falls back to the next configured provider in the chain (existing behaviour), the run still succeeds.
- The task's `provenance.provider_used` and the console show the provider **actually used**, not the requested one.
- An `agent.fallback` event + `AuditLog` entry records the fallback (`from`, `to`, `reason`).
- `GET /providers/health` shows provider A `unreachable` — from a real probe, not fabricated (FR-110).

**Automated**: `tests/integration/test_org_provider_failure.py`.

---

## Scenario 11 — Disabled agent + full control enforcement (US9 / SC-013)

**Steps**
1. Disable an agent a plan would require (`PUT /agents/control/{name}` as `admin@…`).
2. Submit an objective needing that capability.
3. Re-enable; submit again.
4. Attempt to disable `audit_agent`.

**Expected**
- The CEO records an unavailable-capability `OrganizationalDecision` (approved fallback / wait / reassign / escalate) and **does not** dispatch the disabled agent (SC-013); enforcement holds for all agents incl. the 7 previously `enforced=False`.
- `agent.disabled` / `agent.enabled` events + audit entries; console reflects the real state.
- `audit_agent` disable → refused (FR-122).

**Automated**: `tests/integration/test_org_agent_control.py`.

---

## Scenario 12 — Ad-hoc analysis + omni-channel objective (US8 / SC-022)

**Steps**
1. Web chat: "analyse my portfolio and identify the highest-risk positions" → confirm a run/task is created, real portfolio data + tools used, answer linked to that execution + an `AuditLog` entry.
2. Connected channel (Telegram sandbox / signed request): "run today's research" → confirm a real `OrganizationRun` is created and the reply is the CEO synthesis of that run.
3. Web chat: "what is my current P&L" → answered directly, **no** run created (FR-133).
4. Unmapped channel sender sends an actionable objective → recorded, **not** run (spec A-14).

**Automated**: `tests/integration/test_org_adhoc_and_omnichannel.py`.

---

## Scenario 13 — Non-regression (SC-020) + CI green on clean checkout (SC-019 / BUG-E)

**Steps**
1. `docker compose run --rm app pytest` on a **fresh checkout + fresh volumes** with the new CI seeding steps → green (broker-live tests quarantined behind `-m live`).
2. `docker compose run --rm app sh -c "ruff check src tests && black --check src tests && mypy src && bandit -c pyproject.toml -r src"` → clean.
3. `docker compose run --rm app pip-audit` → 0 known vulns.
4. Run the pre-existing Cypress suite → still green; the pre-existing research-pipeline tests (`test_graph.py`, `test_node_*`) → unchanged and green (FR-152).
5. `build_graph()` standalone tests → unchanged (FR-150).
6. `grep` for the corrected docstrings (`memory_agent.py`, `agents.py`) and the removed stale console caption (BUG-G/H).

**Expected**: all green; zero regressions; every intentional behavioural change has a covering test.

---

## Traceability

| Spec SC / mandatory test | Scenario |
|---|---|
| SC-001, SC-002, SC-015 (concurrency), brief §78 | 2 |
| SC-003 (HITL) | 3 |
| SC-004, SC-005 | 4 |
| SC-007, SC-008, SC-009 | 5 |
| SC-010, SC-011, SC-012, SC-016 (Agent Settings), brief §81 | 6 |
| SC-006 | 7 |
| SC-023 | 8 |
| SC-017 (failure), brief §82 | 9 |
| SC-018 (provider failure), brief §84 | 10 |
| SC-013, brief §83 | 11 |
| SC-014 (conflict) | 2 + 4 (conflict comparator) / `test_org_conflict.py` |
| SC-019, SC-020 | 13 |
| SC-021 (owner-only-objectives E2E), brief §79/§80 | 1 → 2 → 3 chained (`test_org_ceo_e2e.py`) |
| SC-022 | 12 |
