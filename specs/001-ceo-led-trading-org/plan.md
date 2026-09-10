# Implementation Plan: CEO-Led AI Trading Organization

**Branch**: `001-ceo-led-trading-org` | **Date**: 2026-09-10 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-ceo-led-trading-org/spec.md`

## Summary

Turn the existing fixed 13-node research pipeline (plus disconnected scheduled agents) into a **CEO-led organisation**: a durable orchestration layer where the CEO agent decomposes an objective into an **Organizational Plan** of typed **Tasks** with declared **Dependencies**, a **Task Engine** runs independent tasks concurrently and holds dependent ones until their inputs exist, agents exchange structured **Result Artefacts**, the CEO records **Decisions** (including conflict resolution), and a redesigned **Organization Command Center** renders it all live. Human approval becomes a real pre-transition gate; News/Sentiment/Portfolio outputs are wired into research context; data freshness becomes a first-class organisational fact; per-agent prompt-version and provider/model configuration gains a dedicated Settings area (AUTO = today's routing, unchanged).

**Technical approach**: add one new backend module `src/orchestration/` that *wraps and reuses* the existing LangGraph graph, LLM router, SkillRegistry, sandbox, deterministic risk/compliance engines, Qdrant memory, Redis pub/sub, and Postgres. The existing `build_graph()` research pipeline is preserved and invoked *as one composite task* ("run the strategy research sub-graph") plus its safety-ordered stages exposed as individually schedulable tasks where the plan needs parallelism upstream of it. New durable state (runs, plans, tasks, dependencies, artefacts, decisions, approvals, events, agent config, dataset freshness) lives in Postgres via new SQLAlchemy models + Alembic migrations. Live updates reuse the existing WebSocket relay + Redis channels. The frontend adds a `console/` route group and an `agent-settings/` section on the existing Next.js app. No datastore, framework, or safety control is replaced.

Delivery is sliced by the spec's user stories: **US1–US4 (P1)** = the minimum viable organisation (plan → parallel/dependent execution → real approval → context integration); **US5–US8 (P2)** = command centre, agent settings, data-freshness UX, ad-hoc/omni-channel; **US9 (P3)** = full agent-control enforcement.

## Technical Context

**Language/Version**: Python 3.12 (backend, `python:3.12-slim`); TypeScript 5 / Node 20 (frontend, Next.js App Router).

**Primary Dependencies** (all existing, reused): FastAPI, SQLAlchemy 2.0, Pydantic v2, Alembic, `structlog`; LangGraph + `langgraph-checkpoint-postgres` (PostgresSaver); LiteLLM via `src/agents/llm_router.py` + `routing.yaml`; `qdrant-client`; `redis`; Temporal (`temporalio`) for the Monte-Carlo workflow; APScheduler (`src/agents/scheduler.py`); `hvac` (Vault); Prometheus client. Frontend: React 18, Tailwind, shadcn/ui (`base-nova`), Zustand, `@tanstack/react-query`, `framer-motion`, `lightweight-charts`, `diff`.

**New dependencies**: none anticipated. Concurrency uses the Python stdlib (`concurrent.futures.ThreadPoolExecutor` for the synchronous node functions, matching the existing detached-thread execution model) plus a Postgres-row-backed work queue (advisory-lock claim), not a new broker. If a genuinely new library proves necessary during Phase 0 it is added to `pyproject.toml` base deps and the image rebuilt (Docker-only rule).

**Storage**:
- **Postgres** (system of record) — all new orchestration entities (§data-model.md), via new `src/models/orchestration*.py` + Alembic migrations run as the `tradingos` (migration) role.
- **Redis** (ephemeral pub/sub) — a new `organization:events` channel for live console fan-out, alongside the existing `ticks:*` / agent-log channels. No durable state in Redis.
- **Qdrant** (agent memory) — the existing `trading_strategies` / `code_templates` / `news_sentiment` collections; organisational memory (past plans, CEO decisions, lessons) is a new payload class in the existing `trading_strategies` collection or a new `organization_memory` collection — decided in research.md. No second memory platform.
- **LangGraph PostgresSaver** — already present (REL-060); reused so an interrupted run resumes (FR-019).

**Testing**: `pytest` (unit `tests/unit/`, integration `tests/integration/` against the live Docker stack); Cypress (`frontend/cypress/e2e/`) via `cypress/included` on the compose network. All invoked through `docker compose run --rm app ...` / the established Cypress container pattern. CI gates: ruff, black, `mypy --strict`, bandit, gitleaks, `pip-audit`, `alembic upgrade head`, `pytest --cov` + per-module coverage gate, Cypress, Helm lint.

**Target Platform**: single hardened Docker Compose host = production (constitution / Phase 1 ADR 10). Backend served by Uvicorn (`app` :8001 plain, `app-tls` :8443). Frontend Next.js. No separate staging.

**Project Type**: web application (Python backend + Next.js frontend) — Structure Decision below uses the existing two-tree layout.

**Performance Goals**:
- SC-001: the independent phase of a plan completes in ≈ the longest single independent task + scheduling overhead (not the sum).
- SC-007: a backend state change is visible in the console within **~2 s** under normal single-host load (soft target, event-driven, no polling).
- SC-023: restart mid-run → automatic resume, zero completed-task re-execution.
- Concurrency cap: **3** active organization runs by default (`ORG_MAX_CONCURRENT_RUNS`, configurable); excess objectives queue.
- Per-agent LLM behaviour on AUTO must be byte-for-byte identical to today (SC-010).

**Constraints**:
- Deterministic risk engine, kill switch, compliance checks, RBAC, broker controls, and the immutable audit chain retain final authority; the orchestration layer never overrides, bypasses, or reorders around them (FR-050/051; constitution principle IV).
- No code path may place a live order or move real funds automatically (FR-056).
- Strategy safety order (validate → comply → backtest → evaluate → risk) and signal safety order (deterministic risk → compliance → governed execution) are preserved regardless of parallelism (FR-051).
- Concurrency is allowed only for operations that do not race on shared mutable state; the kill-switch singleton and the shared sandbox pool remain serialised (spec Assumption A-8).
- All execution in Docker; no host Python (constitution principle II).
- Secrets (LLM/broker keys) stay in Vault; none enter source (constitution principle VII).
- `mypy --strict` clean; ruff/black clean; `src.`-prefixed imports.

**Scale/Scope**: ~24 active agents across 7 departments; ~12 new persistent entities; ≤3 concurrent organization runs, each with an expected 8–20 tasks; 9 user stories, ~95 functional requirements; ~10 new/changed REST endpoint groups; 1 new Redis channel + 1 extended WS stream; ~10 new frontend routes/panels + a new Settings section; target net-new backend code on the order of a mid-size module (planner, task engine, dependency resolver, event emitter, artefact store, config service).

## Constitution Check

*GATE: must pass before Phase 0. Re-checked after Phase 1 (below).*

| # | Principle | Assessment | Gate |
|---|---|---|---|
| I | **Spec-Driven & Traceable** | This plan derives from `spec.md` (itself derived from the audit + brief); every FR maps to a story and the Audit Traceability table maps BUG-A…I + P0–P3. `tasks.md` (next) will carry the task→FR→test links. ERDTM update is a delivery task. | **PASS** |
| II | **Docker-Only Execution** | All build/test/lint/migrations/scripts run via `docker compose run --rm app …` / the Cypress container. No new host tooling. | **PASS** |
| III | **Quality Gates Non-Negotiable** | Plan requires ruff + black + `mypy --strict` + bandit + gitleaks + pip-audit + `alembic upgrade head` + `pytest --cov` + per-module gate + Cypress green **on a clean checkout** (FR-161 / SC-019). No gate weakened; suppressions require an inline reviewed reason. | **PASS** |
| IV | **Safety-Critical Trading Controls (NON-NEGOTIABLE)** | The orchestration layer is strictly *above* the deterministic engines. FR-050/051 forbid override/bypass/reorder. The CEO planner may only sequence tasks *around* the existing safety-ordered sub-graph, never inside it; compliance/risk/kill-switch nodes keep veto authority; no new automated `place_order` path (FR-056). Parallelism excludes the kill-switch singleton and shared sandbox (A-8). A dedicated design task adds a test asserting the CEO cannot reorder the strategy safety chain. | **PASS** (guarded) |
| V | **Module Storage Ownership** | New durable state → Postgres only, owned by a new `src/orchestration/` + `src/models/` classes; live fan-out → Redis pub/sub (ephemeral, existing pattern); organisational memory → existing Qdrant. No module reads another's store directly — the orchestration layer calls existing module interfaces (`get_session()`, the graph, the SkillRegistry, `strategy_memory`, the risk/compliance engines). No new datastore. | **PASS** |
| VI | **Real Integrations, Honest Status** | FR-044 (reduced-coverage marker), FR-063 (no synthetic market data), FR-071 (expose source limits), FR-081/089 (no simulated graph activity, no hard-coded status), FR-110 (real provider health). Data-freshness UX surfaces staleness rather than hiding it. Nothing is marked done without its acceptance test passing (constitution principle VI). | **PASS** |
| VII | **Secrets Never in Source** | Provider/model *selection* is stored (Postgres); provider *keys* stay in Vault via the existing `resolve_api_key()`. No key material in code, config, or the new tables. | **PASS** |

**Result: PASS — no violations.** Complexity Tracking table left empty.

**Post-Phase-1 re-check**: after data-model / contracts design (below), re-evaluated — still PASS. The design adds no new datastore, no host tooling, no safety bypass, and no secret in source. One watch item recorded in research.md: the Postgres-row work queue must use advisory locks correctly so concurrent run workers do not double-claim a task (correctness, not a constitution issue).

## Project Structure

### Documentation (this feature)

```text
specs/001-ceo-led-trading-org/
├── plan.md              # This file
├── spec.md              # Feature spec (/speckit-specify + /speckit-clarify)
├── research.md          # Phase 0 — architecture decisions
├── data-model.md        # Phase 1 — entities & relationships
├── quickstart.md        # Phase 1 — runnable validation scenarios
├── contracts/
│   ├── rest-api.md      # New/changed REST endpoint contracts
│   ├── events.md        # Organizational event catalogue + payload shapes
│   └── websocket.md     # Live console stream contract
├── checklists/
│   └── requirements.md  # Spec quality checklist (existing)
└── tasks.md             # Phase 2 — /speckit-tasks (NOT created here)
```

### Source Code (repository root)

```text
TradingOS/
├── src/
│   ├── orchestration/                # NEW — the organisation layer
│   │   ├── __init__.py
│   │   ├── planner.py                # CEO planner: objective -> OrganizationalPlan
│   │   ├── task_engine.py            # scheduler/executor: ready-set, concurrency, waiting
│   │   ├── dependency_resolver.py    # dependency graph, satisfied/blocked evaluation
│   │   ├── run_manager.py            # OrganizationRun lifecycle, concurrency cap, queue, resume
│   │   ├── agent_invoker.py          # capability lookup -> availability check -> dispatch one agent/task
│   │   ├── artefact_store.py         # typed Result Artefact persistence + provenance + consumed/informational
│   │   ├── decisions.py              # CEO decision recording + conflict detection helpers
│   │   ├── events.py                 # OrganizationalEvent emit -> Postgres + Redis + audit
│   │   ├── approvals.py              # pending-approval gate for Backtesting->Paper (FR-052..057)
│   │   ├── freshness.py              # dataset freshness service (wraps src/data/datalake/freshness.py)
│   │   ├── agent_config.py           # per-agent prompt-version + provider/model resolution & audit
│   │   └── capability_registry.py    # extends src/agents/control.py KNOWN_AGENTS with capabilities/health
│   ├── agents/                       # EXISTING — reused; graph.py, nodes/*, llm_router, control.py,
│   │   │                             #   scheduler.py, prompt_registry.py, routing.yaml, tools/
│   │   └── prompt_registry.py        # EXTENDED — DB-backed prompt versions + activate/rollback API
│   ├── engine/ , data/ , brokers/ , memory/ , core/ , observability/   # EXISTING — reused unchanged
│   ├── models/
│   │   ├── orchestration.py          # NEW — OrganizationRun, OrganizationalPlan, Task, TaskDependency,
│   │   │                             #   ResultArtefact, OrganizationalDecision, OrganizationalEvent
│   │   ├── approval.py               # NEW — ApprovalRequest (or extend existing strategy models)
│   │   ├── agent_config.py           # NEW — AgentConfig, PromptVersion, (ProviderModelConfig is derived)
│   │   ├── dataset_freshness.py      # NEW — DatasetFreshnessRecord
│   │   └── ...                       # EXISTING models reused (Strategy, AgentRun, AuditLog, ...)
│   ├── api/routers/
│   │   ├── organization.py           # NEW — runs, plan, tasks, dependencies, decisions, events
│   │   ├── approvals.py              # NEW — pending list, approve, reject
│   │   ├── agent_settings.py         # NEW — per-agent prompt versions + provider/model + skills + test panel
│   │   ├── provider_models.py        # NEW — configured providers/models + health
│   │   ├── agents.py                 # EXTENDED — deprecate stale caption source; add non-graph activity
│   │   └── chat.py , webhooks.py     # EXTENDED — route "do something" objectives into the organisation
│   └── workers/  scheduler.py hooks  # EXTENDED — schedule triggers create OrganizationRuns
├── alembic/versions/                 # NEW migrations for the tables above (run as tradingos role)
├── frontend/src/
│   ├── app/(app)/
│   │   ├── console/                  # NEW route group — Organization Command Center
│   │   │   ├── page.tsx              #   home (org health, running/waiting/blocked, approvals, freshness)
│   │   │   ├── runs/[runId]/page.tsx #   run workspace: org task graph + activity stream + replay
│   │   │   └── agents/[agentId]/page.tsx  # uniform agent detail view
│   │   ├── agents/page.tsx           # EXISTING — folded into /console or kept as redirect
│   │   └── settings/
│   │       └── agents/[agentId]/page.tsx  # NEW — Agent Settings (prompt versions, provider/model, skills)
│   ├── components/
│   │   ├── console/                  # NEW — OrganizationOverview, OrgTaskGraph, ActivityStream,
│   │   │                             #   AgentDetail, TaskInspector, DependencyPanel, DecisionHistory,
│   │   │                             #   ApprovalQueue, RunReplay, DepartmentView
│   │   └── agent-settings/           # NEW — PromptVersionHistory, PromptDiff, PromptEditor,
│   │                                 #   ProviderSelector, ModelSelector, ProviderHealth, TestPanel
│   ├── hooks/                        # NEW — useOrganizationStream, useOrgRun, useAgentDetail
│   └── lib/                          # EXTENDED — api client, permissions map (SA-only agent config)
└── frontend/cypress/e2e/            # NEW specs — org_run.cy.ts, approval_gate.cy.ts,
                                      #   agent_settings.cy.ts, console_live.cy.ts
```

**Structure Decision**: Two-tree web app, unchanged. All new backend logic is isolated in **`src/orchestration/`** so the existing `src/agents/` pipeline, engines, and data modules stay reusable and independently testable; the orchestration layer is a *caller* of those modules, honouring module storage ownership (principle V). Frontend adds a **`console/`** route group and an **Agent Settings** section, reusing the existing shell, design tokens, shadcn primitives, WebSocket hooks, and RBAC/`<Gated>` pattern.

## Phased Delivery (maps the brief's 16 phases onto this design)

| Brief phase | This plan | Spec stories | Key artefacts |
|---|---|---|---|
| 1 Task foundation | `src/models/orchestration.py` + migrations; `Task`/`TaskDependency`/`OrganizationRun`/`OrganizationalPlan` schemas; lifecycle enum | US1, US2 | data-model.md |
| 2 CEO planner/orchestrator | `planner.py` (LLM plan generation → validated `OrganizationalPlan`); `run_manager.py` (lifecycle, cap=3, queue, resume) | US1 | contracts/rest-api.md §runs |
| 3 Dependency engine | `dependency_resolver.py` (acyclic check, ready-set, blocked-reason) | US2 | data-model.md §TaskDependency |
| 4 Parallel execution | `task_engine.py` (ThreadPoolExecutor + Postgres advisory-lock claim; concurrency-safe task-type allowlist) | US2 | research.md §Task engine |
| 5 Agent collaboration | `decisions.py` (delegation/handoff/review/feedback/escalation as structured rows); conflict detection; peer-review hooks | US2, US4 | contracts/events.md |
| 6 Existing agent integration | `agent_invoker.py` wraps `build_graph()` + individual nodes + scheduled agents (News/Sentiment/Portfolio) as tasks; context-assembly artefact feeds `strategy_generator` | US4 | research.md §Reuse |
| 7 Audit remediation | BUG-A (freshness `freshness.py`), BUG-D (implement `fetch_global_indices`, `query_news_sentiment`), BUG-E (CI seeding), BUG-F (live-pipeline Order persistence), BUG-G/H (console caption + docstrings), BUG-I (lifecycle enum) | US7 + cross-cutting | quickstart.md |
| 8 HITL | `approvals.py` + `ApprovalRequest`; deployment node writes `PendingPaperApproval`, `approve` performs the transition (SA/PM only) | US3 | contracts/rest-api.md §approvals |
| 9 Realtime events | `events.py` → Postgres + Redis `organization:events` + WS relay; extend `/stream/agents` | US5 | contracts/websocket.md |
| 10 Agent Console UX | `console/` route group + components; live org task graph from real state; run replay; uniform agent detail | US5 | contracts/rest-api.md §console |
| 11 Agent Settings | `settings/agents/[id]`; DB-backed prompt versions; skills panel | US6 | data-model.md §PromptVersion |
| 12 Provider/model routing | `agent_config.py` resolution (global→agent→task→fallback precedence); `provider_models.py` health; AUTO default unchanged | US6 | research.md §Provider/model |
| 13 Ad-hoc agent workflows | `chat.py`/`webhooks.py` route "analyse portfolio / explain drawdown / run research" into `run_manager.create_run(...)`; pure lookups answered directly | US8 | quickstart.md §ad-hoc |
| 14 Reliability | per-LLM-call timeout; zombie-run reaper on startup; resume-from-checkpoint proof; provider-failure transparency | edge cases, SC-017/018/023 | quickstart.md §failure |
| 15 Testing | unit + integration + Cypress per the mandated tests | all | quickstart.md |
| 16 E2E validation | the mandatory concurrency, CEO, Agent-Settings, failure, provider-failure scenarios all green | SC-015/016/017/018 | quickstart.md |

## Complexity Tracking

*No constitution violations — table intentionally empty.*
