# Contract — REST API (new & changed)

**Feature**: CEO-Led AI Trading Organization | **Date**: 2026-09-10

Conventions follow the existing codebase: FastAPI routers under `src/api/routers/`, prefix `/api/v1`, Pydantic v2 request/response models, RBAC via the Casbin `require_role` dependency + `policy.csv` rows, GET endpoints open to any authenticated role unless noted, mutating endpoints gated. Every mutating call writes an `AuditLog` entry. All new routes need matching `policy.csv` rows (the class of bug REL-019/021/055 repeatedly hit).

Roles: `SystemAdministrator` (SA), `PortfolioManager` (PM), `RiskManager` (RM), `ReadOnlyAuditor` (RO).

---

## Router: `organization.py` — prefix `/api/v1/organization`

### Runs

| Method & path | Auth | Purpose | Notes |
|---|---|---|---|
| `POST /runs` | SA, PM, RM | Create an organization run from an objective (FR-001) | Body: `{objective, source?, constraints?}`. 202 + `{run_id, status}`. If active runs ≥ cap → `status="queued"` with `queue_position` (FR-009). |
| `GET /runs` | any | List runs (filter `status`, `source`, `limit`, `cursor`) | Newest first. |
| `GET /runs/{run_id}` | any | Run detail: status, objective, plan summary, task counts by status, pending approvals, produced strategy, result summary | |
| `GET /runs/{run_id}/plan` | any | The `OrganizationalPlan`: tasks, assignments, dependency graph, constraints, safety requirements (FR-002, US1 test) | |
| `GET /runs/{run_id}/tasks` | any | All tasks with lifecycle state, timings, `ran_concurrently`, `dependency_wait_seconds` (FR-016) | |
| `GET /runs/{run_id}/tasks/{task_id}` | any | One task: inputs, received inputs, required datasets + freshness, blocked/failure reason, linked `agent_run_id`, artefact (FR-070 waiting UX, FR-084 error UX) | |
| `GET /runs/{run_id}/dependencies` | any | Dependency edges with `state`, prerequisite owner, `satisfied_at` (FR-041 dependency viz) | |
| `GET /runs/{run_id}/artefacts` | any | Result artefacts with provenance + `disposition` + `coverage` (SC-004, FR-030/031) | |
| `GET /runs/{run_id}/decisions` | any | `OrganizationalDecision` list (operational summaries, FR-023) | No private reasoning in payload. |
| `GET /runs/{run_id}/events` | any | Ordered `OrganizationalEvent` list — the replay source (FR-087) | Supports `after_sequence` for incremental fetch. |
| `POST /runs/{run_id}/pause` | SA, PM, RM | Pause an in-flight run (reuses existing pause primitive) | |
| `POST /runs/{run_id}/resume` | SA, PM, RM | Resume from last checkpoint (FR-019) | |
| `POST /runs/{run_id}/cancel` | SA, PM, RM | Cancel; in-flight tasks → `cancelled`, dependents not falsely completed | |
| `POST /runs/{run_id}/replan` | SA, PM | Ask the CEO to re-plan the remainder (records a `re_plan` decision; supersedes open tasks) | |

### Attention & conflicts

| `GET /attention` | any | Cross-run queue: runs `stalled`, tasks `blocked`/`escalated`, conflicts awaiting a CEO decision, escalations to a human (FR-022, research R20) |
| `POST /decisions/{decision_id}/resolve` | SA, PM, RM | A human resolves an escalated conflict/decision; records `resolved_by` + audit |

---

## Router: `approvals.py` — prefix `/api/v1/organization/approvals`

| Method & path | Auth | Purpose |
|---|---|---|
| `GET /` | SA, PM, RM, RO | List `ApprovalRequest` rows (default `status=pending`) — the approvals queue (US3, US5) |
| `GET /{id}` | SA, PM, RM, RO | One request + the `DeploymentRecommendation` artefact + backtest/optimisation/risk/compliance artefacts + Go-Live gate status (US3 review panel) |
| `POST /{id}/approve` | **SA, PM only** (clarify Q1) | Transition subject strategy `PendingPaperApproval → PaperTrading`; write audit (actor, time); emit `approval.approved` (FR-052/053) |
| `POST /{id}/reject` | **SA, PM only** | Body `{reason}` **required**; strategy → `Deprecated`; audit; emit `approval.rejected` (FR-053/054) |

Any other role on `approve`/`reject` → 403 + audited denial. No timeout auto-resolves (FR-057).

Paper→Live remains the **unchanged** existing `POST /api/v1/strategies/{id}/promote` (SA, PM) — not part of this contract (FR-055).

---

## Router: `agent_settings.py` — prefix `/api/v1/agents/{agent_slug}/config`

| Method & path | Auth | Purpose |
|---|---|---|
| `GET /` | any (view) | Agent config: `is_llm_backed`, `provider_model_mode`, effective provider/model + which precedence level applied (FR-106), active prompt versions, skills (enabled/disabled), permissions (FR-082, FR-109). Deterministic agents return `provider_model: "deterministic"` (clarify Q5). |
| `GET /prompts` | any (view) | Prompt version history per kind: version, author, dates, change summary, `is_active` (FR-101) |
| `GET /prompts/{kind}/{version}` | any (view) | One version's content (for diff view, FR-101) |
| `POST /prompts/{kind}` | **SA only** (clarify Q4) | Create a new (inactive) prompt version. Body `{content, change_summary}`. Validated; audited. (FR-103) |
| `POST /prompts/{kind}/{version}/activate` | **SA only** | Activate a version (clears prior active); effective next run, no redeploy; audit before/after (FR-102/103/107) |
| `POST /prompts/{kind}/{version}/rollback` | **SA only** | Convenience alias for activating an older version; audited |
| `PUT /provider-model` | **SA only** | Body `{mode: "AUTO" \| "CUSTOM", provider?, model?}`. `CUSTOM` requires a configured+valid pair (FR-105); else 422. Audit before/after (FR-107). Rejected for deterministic agents (422). |
| `POST /test` | **SA only** | Test panel: body `{kind, version?, provider?, model?}`. Runs the prompt+model against the real router **without activating**; returns `{provider, model, latency_ms, structured_output_valid, tool_compatible, token_cost?, errors[]}` (FR-108). |
| `PUT /skills/{skill_name}` | **SA only** | Enable/disable a skill for this agent; audited (FR-109) |

---

## Router: `provider_models.py` — prefix `/api/v1/providers`

| Method & path | Auth | Purpose |
|---|---|---|
| `GET /` | any (view) | Configured providers + their valid models (from `routing.yaml` + Vault key presence). Only `configured && key_present` entries (FR-105). |
| `GET /health` | any (view) | Per provider/model: `availability` (connected/degraded/unreachable), `p50_latency_ms`, `last_failure_at`, `in_fallback` — **real signals only** (FR-110, constitution VI) |

---

## Router: `agents.py` (existing) — changes

| Change | Reason |
|---|---|
| `GET /agents/graph` | keep; console derives the org graph caption from this + live run state, **not** a hard-coded string (FR-089, BUG-G) |
| `GET /agents` (registry) | extend each row with `department`, `capabilities`, `is_llm_backed`, `health`, `last_execution`, `next_scheduled_execution` (FR-016 registry fields, FR-086) |
| `GET /agents/{id}/activity` | **new** — recent activity for a non-graph agent (News/Sentiment/Portfolio/Notification): last runs, outputs, whether consumed (FR-082, BUG-C console gap) |
| `PUT /agents/control/{name}` | keep (REL-019); ensure enforcement across **all** agents incl. the 7 currently `enforced=False` (FR-120/121, US9); audit-agent refusal kept (FR-122) |
| `POST /agents/runs/{id}/approve` \| `/reject` | **removed** — superseded by `approvals.py` real gate (BUG-B). `retry` kept. |
| stale docstrings in `memory_agent.py`, `agents.py` | corrected (BUG-H) |

---

## Router: `chat.py` / `webhooks.py` (existing) — changes

| Change | Reason |
|---|---|
| Inbound message classifier | actionable objective → `run_manager.create_run(objective, source=<channel>, requested_by=<mapped identity>)`; reply = CEO synthesis of that run (FR-130/132). Pure data lookup → answered directly, no run (FR-133). |
| Channel identity | actionable objectives require the sender mapped to an authorised identity (existing `NOTIFICATION_CHANNELS`, SEC-030); unmapped → recorded, not run (spec A-14) |

---

## Error model (all new routes)

Standard FastAPI `HTTPException` with JSON `{detail}`; 401 unauthenticated, 403 (audited) for role failure, 404 unknown id, 409 for an illegal state transition (e.g. approving an already-decided request), 422 for validation (invalid provider/model, cyclic plan, missing reason on reject). Broker/provider failures surface as 502/503 with a clear message, never a raw 500 (BUG-F-adjacent robustness).
