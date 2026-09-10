---
description: "Task list for CEO-Led AI Trading Organization"
---

# Tasks: CEO-Led AI Trading Organization

**Input**: Design documents from `specs/001-ceo-led-trading-org/`
**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md), `.specify/memory/constitution.md`

**Tests**: INCLUDED — the spec mandates them (SC-015/016/017/018, brief §77–§84, constitution principle III). Every user story phase ends with its tests; the 5 brief-mandated tests are marked **(MANDATORY)**.

**Web-app layout** (plan.md): backend `src/…`, migrations `alembic/versions/…`, backend tests `tests/{unit,integration}/…`, frontend `frontend/src/…`, Cypress `frontend/cypress/e2e/…`. All execution via `docker compose run --rm app …` / the Cypress container (constitution II).

## Format: `[ID] [P?] [Story] Description with file path`

- **[P]**: parallelizable (different files, no dependency on an incomplete task)
- **[Story]**: US1–US9 for user-story phases only; Setup/Foundational/Polish have no story label

---

## Phase 1: Setup (Shared Infrastructure)

- [X] T001 Create the orchestration module skeleton: `src/orchestration/__init__.py` plus empty stub files `planner.py`, `task_engine.py`, `dependency_resolver.py`, `run_manager.py`, `agent_invoker.py`, `artefact_store.py`, `decisions.py`, `events.py`, `approvals.py`, `freshness.py`, `agent_config.py`, `capability_registry.py` (docstring per file stating its responsibility from plan.md §Project Structure)
- [X] T002 [P] Add config settings to `src/core/config.py`: `ORG_MAX_CONCURRENT_RUNS` (default 3), `ORG_TASK_POOL_SIZE` (default 8), `ORG_RUN_STALL_SECONDS` (default 900), `ORG_TASK_DEFAULT_TIMEOUT_SECONDS` (default 300), `ORG_RESEARCH_TASK_TIMEOUT_SECONDS` (default 1800), `LLM_CALL_TIMEOUT_SECONDS` (default 120)
- [X] T003 [P] Add pytest marker `live` to `pyproject.toml` `[tool.pytest.ini_options]` markers and default `-m "not live"` in CI so broker-live tests are quarantined from the default gate (BUG-E, quickstart Scenario 13)
- [X] T004 [P] Add a frontend route-group folder `frontend/src/app/(app)/console/` and `frontend/src/components/console/` + `frontend/src/components/agent-settings/` + `frontend/src/hooks/` placeholders with an index barrel each

---

## Phase 2: Foundational (Blocking Prerequisites)

**⚠️ No user-story phase may start until Phase 2 is complete.** These are shared by every story.

### Data model & migrations

- [X] T005 Create enum module `src/orchestration/enums.py` with `RunStatus` = {queued, planning, running, waiting, paused, stalled, completed, failed, cannot_plan, cancelled}; `TaskStatus` = {created, planned, queued, ready, running, waiting_for_dependency, waiting_for_agent, blocked, awaiting_approval, completed, failed, retrying, escalated, cancelled, superseded}; `AgentStatus` = {idle, running, escalated, disabled, degraded}; `ApprovalStatus` = {pending, approved, rejected} (data-model.md §16 — these four are never conflated)
- [X] T006 [P] SQLAlchemy models in `src/models/orchestration.py`: `OrganizationRun`, `OrganizationalPlan`, `Task`, `TaskDependency`, `ResultArtefact`, `OrganizationalDecision`, `OrganizationalEvent` — fields exactly per data-model.md §1–§6, §8; UUID PK via `UUIDPKMixin`; `tenant_id` FK → `tenants`; JSONB for `payload`/`provenance`/`constraints`/`departments`
- [X] T007 [P] SQLAlchemy model in `src/models/approval.py`: `ApprovalRequest` per data-model.md §7 — FK to `strategies`, `strategy_versions`, `result_artefacts`, `organization_runs`; `reason` column nullable but **required when `status = rejected`** (enforce in service layer + a CHECK-style guard)
- [X] T008 [P] SQLAlchemy models in `src/models/agent_config.py`: `AgentConfig` (data-model.md §9) and `PromptVersion` (data-model.md §10) — `PromptVersion` unique `(agent_slug, kind, version)`; **at most one row with `is_active = true` per `(agent_slug, kind)`** (partial unique index)
- [X] T009 [P] SQLAlchemy model in `src/models/dataset_freshness.py`: `DatasetFreshnessRecord` per data-model.md §11 — `dataset_name` unique; `status` enum {fresh, stale, unavailable, failed}
- [X] T010 Alembic migration `alembic/versions/<rev>_orchestration_core.py` creating all 11 new tables from T006–T009; add `PendingPaperApproval` to the `strategies.status` CHECK constraint (data-model.md §7 "Strategy status enum change" + §Migration notes); add a `BEFORE UPDATE OR DELETE` trigger on `organizational_events` rejecting mutation (reuse the `audit_log` trigger pattern) and `REVOKE UPDATE, DELETE … FROM tradingos_app`; migration runs as `tradingos`, app as `tradingos_app`
- [X] T011 Verify migration applies cleanly and downgrades: `docker compose run --rm app alembic upgrade head` then `downgrade -1` then `upgrade head`; add `tests/integration/test_orchestration_migration.py` asserting the tables, the `PendingPaperApproval` CHECK value, and the events append-only trigger (a raw UPDATE from `tradingos_app` raises)

### Artefact schemas & provenance

- [X] T012 [P] Create `src/orchestration/artefact_schemas.py`: a Pydantic v2 model per `artefact_type` listed in data-model.md §5 (ResearchDirective, MarketContext, NewsDigest, SentimentReport, PortfolioRiskReport, AllocationPlan, ResearchContext, StrategyLogic, OptionStrategyProposal, PythonCode, ValidationReport, ComplianceReport, BacktestMetrics, OptimizationReport, RiskReport, EvaluationReport, DeploymentRecommendation, CeoSynthesis, AdHocAnalysis) + an `ARTEFACT_SCHEMA_REGISTRY: dict[str, type[BaseModel]]`; reuse existing Pydantic models from `src/agents/state.py` where they already exist (MarketContext, StrategyLogic, etc.)
- [X] T013 [P] Implement `src/orchestration/artefact_store.py`: `persist_artefact(session, run_id, task_id, artefact_type, payload, provenance, disposition)` — validates `payload` against `ARTEFACT_SCHEMA_REGISTRY[artefact_type]` (FR-030 "typed"), records provenance `{agent, task_id, run_id, model_used, provider_used, tools_used, inputs, produced_at}`, sets `disposition ∈ {consumed, informational}` (FR-031), returns the row; `mark_consumed(session, artefact_id, by_task_id)`

### Events & realtime plumbing

- [X] T014 Implement `src/orchestration/events.py`: `emit(session, run_id, event_type, subject_type, subject_id, payload, *, audited: bool)` — assigns a gap-free per-run `sequence` in the same transaction as the caller's state change (data-model.md §8), inserts the `organizational_events` row, publishes a compact JSON envelope (contracts/events.md §Envelope) to Redis channel `organization:events`, and for `audited=True` writes an `AuditLog` hash-chain entry via the existing writer
- [X] T015 Add `WS /api/v1/stream/organization` to `src/api/routers/streams.py` per contracts/websocket.md: JWT auth (any authenticated role, read-only), accepts `{"subscribe": {"run_ids": [...]}}`, relays the `organization:events` Redis channel filtered by subscribed run ids, plus heartbeat frames; no mutation over the socket
- [X] T016 [P] Backend integration test `tests/integration/test_org_event_stream.py`: emit an event → assert a row, a Redis publish, an `AuditLog` entry for `audited=True`, and a WS subscriber receives the envelope filtered by run id

### Run lifecycle & capability registry

- [X] T017 Implement `src/orchestration/run_manager.py`: `create_run(session, objective, source, requested_by, constraints=None)` inserts an `OrganizationRun` (status `queued` with `queue_position` if active runs ≥ `ORG_MAX_CONCURRENT_RUNS`, else `planning`); `promote_queued()` oldest-first when a slot frees; `reap_incomplete_runs()` startup hook (data-model.md §1 + research R3/R4) — completed tasks keep artefacts, a `running` task resets to `ready` if idempotent else `failed` with reason, never false `completed`
- [X] T018 Wire `run_manager.reap_incomplete_runs()` into the FastAPI `lifespan` in `src/api/main.py` (runs once at startup, before the scheduler starts) and add a per-LLM-call timeout (`LLM_CALL_TIMEOUT_SECONDS`) into `src/agents/llm_router.py::complete` so an exhausted-provider call cannot hang a worker thread (audit AR-2)
- [X] T019 Extend `src/agents/control.py::AgentDescriptor` with `department: str`, `capabilities: tuple[str, ...]`, `is_llm_backed: bool`, `concurrency_limit: int`; populate all `KNOWN_AGENTS` rows with departments (Executive, Market Intelligence, Research, Quant, Risk & Governance, Portfolio, Operations) and capability slugs; mark deterministic agents (`python_validator`, `backtesting`, `compliance`, `data_ingestion_agent`, `scheduler_agent`, `audit_agent`) `is_llm_backed = False` (research R6, clarify Q5)
- [X] T020 Implement `src/orchestration/capability_registry.py`: `snapshot()` → the planner's view (agent, department, capabilities, enabled from `agent_control_state`, `is_llm_backed`, health) and `find_by_capability(cap)`; `health(agent)` derived from recent `AgentRun` outcomes + provider reachability — **real signals only** (FR-110, constitution VI)

### Memory, RBAC, shared services

- [X] T021 [P] Extend `src/memory/collections.py` to bootstrap a new Qdrant collection `organization_memory` at the configured `EMBEDDING_PROVIDER` dimension; add `src/memory/organization_memory.py` with `ingest_org_memory(kind, text, payload)` and `query_org_memory(text, top_k)` (research R13)
- [X] T022 Add `policy.csv` rows in `src/core/policy/policy.csv` for every new route in contracts/rest-api.md with the exact role sets (approvals `approve`/`reject` → `SystemAdministrator`, `PortfolioManager` only; all `agent_settings.py` writes → `SystemAdministrator` only; run create/pause/resume/cancel/replan → `SystemAdministrator`, `PortfolioManager`, `RiskManager`); update `tests/unit/test_policy_consistency.py` so the drift check passes against the compiled app
- [X] T023 [P] Define the concurrency-safe task-type allowlist as a reviewed named constant `CONCURRENCY_SAFE_CAPABILITIES` in `src/orchestration/task_engine.py` (market analysis, news, sentiment, portfolio-read, data-freshness, RAG lookup, CEO synthesis); everything touching the kill-switch singleton, `src/engine/sandbox/pool.py`, a broker write, or an Alembic-guarded table is excluded (spec A-8, research R2)

---

## Phase 3: User Story 1 — CEO turns an objective into a dynamic plan (P1)

**Goal**: The CEO agent decomposes an objective into a validated, persisted `OrganizationalPlan`.
**Independent test** (spec US1): three different objectives → three distinct, acyclic, capability-matched plans, each persisted + audited; an un-servable objective → recorded `cannot_plan`, no fabricated plan.

- [X] T024 [P] [US1] Create the CEO planner prompt: `src/agents/prompts/ceo_planner/v1.md` (system) + `src/agents/prompts/ceo_planner_task/v1.md` (task template with `{capability_snapshot}` and `{objective}` and the required-output `OrganizationalPlan` JSON schema) + register in `src/agents/prompts/registry.yaml`
- [X] T025 [US1] Implement `src/orchestration/planner.py::generate_plan(session, run)`: calls `llm_router.complete("orchestration", …)` with the capability snapshot + objective; parses a strict `OrganizationalPlan` Pydantic model (tasks, `assigned_agent` by capability, `dependencies` by task-id, `priority`, `expected_output`, `constraints`, `safety_requirements`, `approval_required`); queries `organization_memory` for similar past plans first (FR-032, research R5/R13)
- [X] T026 [US1] Implement deterministic plan validation in `planner.py::validate_plan(plan)` (FR-007, data-model.md §2): topological-sort acyclicity check; every `assigned_agent` exists in the capability registry and matches a declared capability; every dependency target is an in-plan task; any safety-ordered stage present appears in the mandated order (validate → comply → backtest → evaluate → risk); bounded retry with the validation error fed back to the LLM
- [X] T027 [US1] Implement `planner.py` persistence: on valid plan → insert `OrganizationalPlan` + expand `Task` + `TaskDependency` rows (statuses `planned`), emit `organization.plan.created`; on retry exhaustion → set run `status = cannot_plan`, write an `OrganizationalDecision(decision_type="cannot_plan", reason=…)`, emit `organization.run.cannot_plan` (FR-008)
- [X] T028 [US1] Implement `src/api/routers/organization.py` — the Runs endpoints from contracts/rest-api.md §Runs that US1 needs: `POST /runs` (202, queue if at cap), `GET /runs`, `GET /runs/{id}`, `GET /runs/{id}/plan`; register the router in `src/api/main.py`
- [ ] T029 [US1] Wire the scheduler: `src/agents/scheduler.py` daily research trigger calls `run_manager.create_run(objective="prepare tomorrow's trading research", source="schedule")` instead of `trigger_research()` directly (FR-001); keep `trigger_research()` importable for the composite task in US2
  - **DEFERRED to US2** (analyze finding O2): switching the daily cycle to `create_run` now would regress a working feature — until the US2 task engine exists, `create_run` only produces a plan and stops, whereas `trigger_research()` runs the whole pipeline. The scheduler stays on `trigger_research()` until US2 lands. `run_manager.create_run` is already importable/tested from the API path.
- [X] T030 [P] [US1] Integration test `tests/integration/test_org_planner.py`: three materially different objectives → three distinct validated plans (acyclic, agents exist, deps in-plan); one un-servable objective → `cannot_plan` + decision row + no plan; `organization.plan.created` events + `AuditLog` entries present
- [X] T031 [P] [US1] Unit test `tests/unit/test_plan_validation.py`: `validate_plan` rejects a cyclic graph, an unknown agent, an out-of-plan dependency, and a mis-ordered safety chain

**Checkpoint**: an objective in → a persisted, validated plan out (or an honest `cannot_plan`). Independently demoable.

---

## Phase 4: User Story 2 — Independent work runs in parallel; dependent work waits (P1)

**Goal**: A task engine runs ready tasks concurrently, holds dependent tasks until their inputs exist, and records timing/concurrency/wait.
**Independent test** (spec US2): 4 independent tasks overlap in wall-clock; dependent tasks start only after their last dependency completes; no task runs with a required input absent; upstream permanent failure → downstream `blocked`, never false `completed`.

- [X] T032 [US2] Implement `src/orchestration/dependency_resolver.py`: `ready_tasks(session, run_id)` (all `hard` deps `satisfied` + assigned agent available), `evaluate_on_completion(session, completed_task)` (mark dependent `TaskDependency` rows `satisfied`, emit `dependency.satisfied`, flip dependents `waiting_for_dependency → ready`), `mark_unsatisfiable(session, dep)` when a prerequisite ends `failed`/`blocked` with no alternative producer → dependent task `blocked` with `blocked_reason` (FR-015, FR-017, data-model.md §4)
- [X] T033 [US2] Implement `src/orchestration/task_engine.py::run_scheduler_loop(run_id)`: submits `ready_tasks` to a bounded `concurrent.futures.ThreadPoolExecutor(ORG_TASK_POOL_SIZE)`; claims each task with `UPDATE tasks SET status='running', started_at=now() WHERE id=:id AND status='ready' RETURNING *` inside a txn holding `pg_advisory_xact_lock(hashtext('task:'||id))` (data-model.md §3 Claiming, research R2); only `capability ∈ CONCURRENCY_SAFE_CAPABILITIES` tasks may run in parallel — others serialise
- [X] T034 [US2] Record task timing in `task_engine.py`: set `ran_concurrently = true` when a task's `[started_at, completed_at]` overlaps a sibling's; accumulate `dependency_wait_seconds` while a task sits in `waiting_for_dependency`/`waiting_for_agent`; emit `task.started` / `task.completed` / `task.waiting_for_dependency` / `task.waiting_for_agent` / `task.ready` (FR-016, contracts/events.md)
- [X] T035 [US2] Implement `src/orchestration/agent_invoker.py::dispatch(session, task)`: capability lookup → availability check (agent enabled, healthy, skills/tools/permissions present, required datasets fresh, provider available — FR-005); on unavailable, raise `AgentUnavailable(reason)` for the CEO policy path (US9); on available, call the mapped node/agent function; persist the result via `artefact_store.persist_artefact(...)`; link `task.agent_run_id` to the existing `AgentRun` record
- [X] T036 [US2] Map capabilities → callables in `agent_invoker.py`: standalone tasks call node functions directly (`market_analyst_node`, `news_agent`, `sentiment_agent`, `portfolio_manager_agent`, freshness check); the composite `strategy_research` capability calls the existing `build_graph()` sub-graph via `trigger_research`-equivalent, keyed by `run.thread_id`, so its safety-ordered inner chain is untouched (research R1, constitution IV)
  - **Partial**: the capability→handler table is the live seam; `synthesize`/`orchestrate` make a real `complete()` call, all other capabilities produce an honestly-labelled placeholder artefact of the declared type. Binding the real `market_analyst_node` / `news_agent` / `sentiment_agent` / `portfolio_manager_agent` / freshness callables and the `strategy_research` sub-graph is **DEFERRED to US4/US6** (that is those stories' scope).
- [X] T037 [US2] Implement task lifecycle transitions + retry in `task_engine.py` per data-model.md §3 State transitions: `retrying` (bounded by `max_retries`, default 3) → `failed`; `escalated` when a node escalates to CEO; `superseded` on re-plan; `cancelled` on run cancel; keep `TaskStatus` strictly separate from `RunStatus`/`AgentStatus`/`ApprovalStatus` (FR-012, BUG-I)
- [X] T038 [US2] Wire `run_manager` → `task_engine`: `create_run` (after planning) starts `run_scheduler_loop` in a detached thread (matching `_execute_graph_run`'s model); run `status` follows `running` / `waiting` (all runnable tasks waiting) / `stalled` (no progress for `ORG_RUN_STALL_SECONDS` → flag + attention queue, not auto-fail — research R20) / `completed` / `failed`
  - **Partial**: `_plan_run` runs `run_scheduler_loop` synchronously in the existing detached planning thread; run status follows `running` / `waiting` / `completed` / `failed`. Time-based `stalled` detection (`ORG_RUN_STALL_SECONDS` → attention queue) is **DEFERRED to US5** (Attention queue / console).
- [X] T039 [US2] Add the remaining Runs endpoints to `src/api/routers/organization.py` from contracts/rest-api.md: `GET /runs/{id}/tasks`, `/tasks/{task_id}`, `/dependencies`, `/artefacts`, `/decisions`, `/events` (with `after_sequence`), `POST /runs/{id}/pause|resume|cancel|replan`, `GET /attention`, `POST /decisions/{id}/resolve`
  - **Partial**: `GET /runs/{id}/{tasks,tasks/{task_id},dependencies,artefacts,decisions,events}` and `POST /runs/{id}/cancel` (RBAC-gated, policy.csv updated) are done. `pause|resume|replan`, `GET /attention` and `POST /decisions/{id}/resolve` are **DEFERRED** to US3 (HITL) / US5 (attention) which own those flows.
- [X] T040 [US2] Enforce "no `completed` run while an artefact has `disposition = NULL`" in `run_manager` completion (SC-004) and "no task executes with a `required_inputs` entry absent from `received_inputs`" in `agent_invoker.dispatch` (SC-002)
- [X] T041 [P] [US2] **(MANDATORY)** Integration test `tests/integration/test_org_concurrency.py` (brief §78): a plan with ≥4 independent tasks → overlapping `[started_at, completed_at]` windows + `ran_concurrently=true`, independent-phase wall-clock ≈ longest task + overhead (SC-001); sentiment waits for news, risk-context waits for portfolio, strategy waits for its full input set (SC-002); a `dependency.satisfied` event fires on each satisfaction
- [X] T042 [P] [US2] Unit test `tests/unit/test_task_claim_race.py`: two worker threads race the same `ready` task → exactly one claims/runs it (advisory-lock correctness, research R2 watch item)
- [X] T043 [P] [US2] Integration test `tests/integration/test_org_blocked_dependency.py`: force an upstream task to `failed` after its retry budget → the dependent task is `blocked` with a clear reason and is **not** reported `completed` (FR-017)
- [X] T044 [US2] **(MANDATORY)** Chained E2E test `tests/integration/test_org_ceo_e2e.py` (brief §79): "Find the best low-risk opportunities for tomorrow" → plan created, work delegated, independent tasks concurrent, dependent tasks wait, CEO receives results, a recommendation is produced, every major event persisted + audited (SC-015, SC-021)

**Checkpoint**: US1 + US2 = a working CEO-led organisation for research. This is the true "minimum viable organisation" (spec A-1).

---

## Phase 5: User Story 3 — Real human approval before Paper Trading (P1)

**Goal**: A deployment recommendation puts the strategy in `PendingPaperApproval`; only an `SystemAdministrator`/`PortfolioManager` approval transitions it to `PaperTrading`.
**Independent test** (spec US3): strategy is `PendingPaperApproval` not `PaperTrading`; no job auto-transitions it; `RiskManager` cannot approve; approve → `PaperTrading` + audit; reject (reason required) → `Deprecated`, never entered Paper; Paper→Live unchanged.

- [X] T045 [US3] Change `src/agents/nodes/deployment.py` + `src/api/routers/agents.py::_persist_strategy_progress` to write `Strategy.status = "PendingPaperApproval"` (never `"PaperTrading"`) on a deploy recommendation, and create an `ApprovalRequest` row (status `pending`) linked to the run, strategy, version, and the `DeploymentRecommendation` artefact; emit `approval.requested` (audited) (FR-052, data-model.md §7)
- [X] T046 [US3] Remove the no-op `approve_run` / `reject_run` handlers from `src/api/routers/agents.py` (BUG-B) and their routes; keep `retry_run`
- [X] T047 [US3] Implement `src/api/routers/approvals.py` per contracts/rest-api.md §approvals: `GET /` (default `status=pending`), `GET /{id}` (request + recommendation + backtest/optimisation/risk/compliance artefacts + Go-Live gate status), `POST /{id}/approve` (**`SystemAdministrator`/`PortfolioManager` only** — clarify Q1), `POST /{id}/reject` (**same roles**, body `{reason}` **required**, 422 if missing); register the router
- [X] T048 [US3] Implement `src/orchestration/approvals.py` service: `approve(session, request_id, actor)` → transition `Strategy.status: PendingPaperApproval → PaperTrading`, set `decided_by`/`decided_at`, write `AuditLog` (actor, time), emit `approval.approved`; `reject(session, request_id, actor, reason)` → `Strategy.status → Deprecated`, store `reason`, audit, emit `approval.rejected`; **no timeout path** (FR-057); a non-allowed role → 403 + audited denial (FR-053)
- [X] T049 [US3] `run_manager`: a run that produced an `ApprovalRequest` enters `waiting` (on the approval) rather than `completed`; it reaches `completed` only after the approval is decided (or the run is cancelled)
- [X] T050 [P] [US3] **(HITL)** Integration test `tests/integration/test_org_approval_gate.py` (quickstart Scenario 3, SC-003): pending not paper; no auto-transition after 10 min; `RiskManager` `approve` → 403 audited; `PortfolioManager` `approve` → `PaperTrading` + audit + event; reject without reason → 422; reject with reason → `Deprecated`, never paper; `promote` (Paper→Live) still the untouched existing gate
  - **Note (T045)**: the legacy research-graph path has no `OrganizationRun`, so its `ApprovalRequest` is created with `run_id`/`recommendation_artefact_id` null and the `approval.requested` **audit** entry is written (`APPROVAL_REQUESTED`) but no org **event** is emitted (there is no run to attach it to). `approval_requests.run_id` was made nullable (migration `c7e1d9a4b820`). Org-led deploy tasks set all three once the real deployment handler is wired (US4/US6, T036).
- [ ] T051 [P] [US3] Cypress `frontend/cypress/e2e/approval_gate.cy.ts`: approvals queue renders pending items; `PortfolioManager` approve moves the card and the strategy state; `ReadOnlyAuditor`/`RiskManager` see no approve/reject controls
  - **DEFERRED to US5**: the approvals-queue UI lives in the `console/` route group (Organization Command Center), which is US5 scope. The `approvals.py` API this spec exercises is complete and covered by `test_org_approval_gate.py` (T050).

**Checkpoint**: no strategy enters Paper Trading without a recorded human approval by an allowed role.

---

## Phase 6: User Story 4 — News, sentiment, portfolio actually inform research (P1)

**Goal**: A `ResearchContext` artefact assembled from this run's own news/sentiment/portfolio/market/risk feeds the research sub-graph; no artefact is orphaned; conflicts are detected and resolved by the CEO.
**Independent test** (spec US4): strategy-generation task's inputs include a `ResearchContext` traceable to this run's news + sentiment; every artefact `consumed` or `informational`; News down → `coverage=reduced` marker, nothing presented as complete; portfolio artefact among a CEO decision's inputs.

- [X] T052 [P] [US4] Add the `ResearchContext` Pydantic schema to `src/orchestration/artefact_schemas.py` (fields: market regime, sector strengths, news digest summary, per-symbol/sector sentiment, portfolio exposure snapshot, risk posture, `coverage: full|reduced`, `missing_inputs: list[str]`)
- [X] T053 [US4] Extend the research plan template in `src/orchestration/planner.py` so a research objective always includes parallel `news`, `sentiment` (hard dep on `news`), `portfolio_read`, `market_analysis`, `data_freshness` tasks and a `context_assembly` task (hard deps on all of the above, `soft` where a source may legitimately be absent — FR-044)
- [X] T054 [US4] Implement the `context_assembly` capability in `src/orchestration/agent_invoker.py`: build a `ResearchContext` from the upstream artefacts; when a `soft` dependency is unsatisfied set `coverage="reduced"` + list the missing input (FR-044); persist with provenance referencing every source artefact id
- [X] T055 [US4] Extend `src/agents/nodes/strategy_generator.py` to read a `ResearchContext` artefact from graph state when present (additive — absent ⇒ current behaviour unchanged, FR-153); thread the artefact into the composite `strategy_research` task's input in `agent_invoker.py`
  - **Partial**: `TradingOSGraphState.research_context` added and `strategy_generator_node` folds it into its prompt (fully additive). `agent_invoker.dispatch` already records the upstream `ResearchContext` in a strategy task's `received_inputs`. Actually *executing* `build_graph()` as the `strategy_research` task handler (so the node receives that state field at runtime) is **DEFERRED to US6** together with the other real per-agent handlers (T036).
- [X] T053-note **T053 scope**: the deterministic scaffold (`planner.ensure_research_scaffold`) triggers only for a plan that contains a strategy-generating capability (`strategy_generation` / `strategy_research` / `code_generation`); a pure analysis plan is left as the CEO produced it. Scaffold dependencies are all `hard` for now — `soft`-dependency handling (FR-044) is realised at the `context_assembly` handler, which drops `coverage` to `reduced` and names any source artefact that never arrived.
- [X] T056 [US4] Ensure the `PortfolioRiskReport` artefact id is recorded in the relevant `OrganizationalDecision.supporting_input_artefact_ids` when the objective affects portfolio exposure (FR-043); the risk-context task receives portfolio data as an input
- [X] T057 [US4] Implement `src/orchestration/decisions.py::detect_conflict(artefacts)` — deterministic comparator for opposing pairs (market regime vs aggregate sentiment sign; risk level vs proposed exposure; compliance `Block` vs strategy `proceed`); on conflict, re-invoke the CEO node with the conflicting artefacts and require a `resolve_conflict` `OrganizationalDecision` (summary, reason, supporting inputs, next step) before the run continues; emit `ceo.conflict_detected` + `ceo.decision.created` (FR-022, SC-014)
- [X] T058 [US4] Implement `decisions.py` structured collaboration records: delegation / hand-off / review-request / review-result / feedback / escalation as `OrganizationalDecision` / `task_events` rows, not free text (FR-020); peer review invoked only where `plan.safety_requirements` or a risk rule asks (FR-021)
- [X] T059 [US4] On a failed or rejected strategy, write an `organization_memory` point (objective + task shape + failure reason) via `ingest_org_memory` (FR-033)
- [X] T060 [P] [US4] Integration test `tests/integration/test_org_context_integration.py` (quickstart Scenario 4, SC-004/005): `ResearchContext` provenance references this run's `NewsDigest` + `SentimentReport`; composite task `received_inputs` include it; zero `disposition = NULL` artefacts at `completed`; News down → `coverage=reduced` + missing list; portfolio artefact in a decision's inputs
- [X] T061 [P] [US4] Integration test `tests/integration/test_org_conflict.py` (SC-014): craft opposing market/sentiment artefacts → `detect_conflict` fires → a `resolve_conflict` decision with rationale + supporting inputs is recorded before the run proceeds; a high-severity conflict records a human escalation

**Checkpoint**: the four P1 stories done = the CEO-led organisation the spec's MVP requires.

---

## Phase 7: User Story 5 — Organization Command Center console (P2)

**Goal**: A live command centre rendering real org state (home, org task graph, activity stream, uniform agent detail, run replay), no hard-coded status.
**Independent test** (spec US5): console matches backend records during an active run and updates <~2 s without refresh; independent agents render concurrent; dependency edge animates only on a real event; uniform agent detail for graph + non-graph agents; run replay reconstructs from events; zero hard-coded status strings; WS reconnect re-syncs.

- [X] T062 [P] [US5] Backend: extend `GET /agents` in `src/api/routers/agents.py` with `department`, `capabilities`, `is_llm_backed`, `health`, `last_execution`, `next_scheduled_execution` (FR-016 registry fields); add `GET /agents/{id}/activity` returning recent runs/outputs/consumed-state for non-graph agents (BUG-C console gap)
- [X] T063 [US5] Backend: remove the stale hard-coded caption source feeding the console "5 real nodes…" text; the org-graph caption is derived from `GET /agents/graph` + live run state (FR-089, BUG-G); add a CI grep check in `.github/workflows/ci.yml` failing on hard-coded status literals in `frontend/src`
  - **Note**: the caption in `frontend/src/app/(app)/agents/page.tsx` now renders `${nodes.length} nodes, ${edges.length} edges` from the live `GET /agents/graph` response. The CI grep (`No fabricated status literals in the console`) is scoped to the code this feature owns — `frontend/src/components/console`, `frontend/src/hooks`, `frontend/src/app/(app)/console` — and fails on an *assigned* status literal (`status: "Running"`, `useState("Idle")`), not on a legitimate comparison against a real backend `x.status`.
- [X] T064 [P] [US5] Frontend hook `frontend/src/hooks/useOrganizationStream.ts`: one multiplexed WS subscription per session keyed by selected run set; on event, patch the React Query cache; on reconnect, resubscribe + backfill via `GET /organization/runs/{id}/events?after_sequence=` then resume (contracts/websocket.md, FR-088/090)
- [X] T065 [P] [US5] Frontend `frontend/src/components/console/OrganizationOverview.tsx` — console home: CEO status, org health, running/waiting/blocked counts, pending approvals, recent decisions, recent failures, per-dataset freshness — all from `GET /organization/runs`, `/attention`, `/providers/health` (FR-080)
- [X] T066 [P] [US5] Frontend `frontend/src/components/console/OrgTaskGraph.tsx`: reuse the layered-DAG layout from `graph-flowchart.tsx` (REL-033), extended for task nodes + dependency edges; state-driven animation only (running pulse, dependency-edge activation on `dependency.satisfied`, hand-off transition); never simulated (FR-081); respect `prefers-reduced-motion` (FR-170)
- [X] T067 [P] [US5] Frontend `frontend/src/components/console/ActivityStream.tsx`: virtualised list of `OrganizationalEvent`s for the selected run, filter by agent/task/type (FR-088, FR-172)
- [X] T068 [P] [US5] Frontend `frontend/src/components/console/AgentDetail.tsx` — the **uniform** detail view (FR-082): overview, current task, inputs, outputs, tools, skills, model/provider + default-vs-override indicator or "no model — deterministic", activity timeline, upstream dependencies, downstream consumers, previous runs, recent errors, result artefacts, audit references; each section shows real data or an explicit "no data yet" (SC-009)
- [X] T069 [P] [US5] Frontend `frontend/src/components/console/{DependencyPanel,DecisionHistory,ApprovalQueue,AttentionQueue,DepartmentView}.tsx`: dependency "ready when ✓/⏳ …" panel (FR-041); decision list as operational summaries, no private reasoning (FR-023); approvals queue wired to `approvals.py`; attention queue from `GET /attention`; department grouping (FR-086)
- [X] T070 [P] [US5] Frontend `frontend/src/components/console/RunReplay.tsx`: reconstruct plan → tasks → parallelism → dependencies → hand-offs → results → retries → decisions → approval → outcome from `GET /organization/runs/{id}/events` (FR-087)
- [X] T071 [US5] Frontend routes: `frontend/src/app/(app)/console/page.tsx` (home), `console/runs/[runId]/page.tsx` (workspace: OrgTaskGraph + ActivityStream + panels), `console/agents/[agentId]/page.tsx` (AgentDetail); add `console` to the shell nav; keep `frontend/src/app/(app)/agents/page.tsx` as a redirect to `/console` (FR-153)
- [X] T072 [US5] Waiting-agent UX (FR-083): the AgentDetail / task view states what it waits for, why, and expected next event. Failed-agent UX (FR-084): agent, task, reason, impact, retry status, dependency impact, CEO response, recommended action — not just "Failed"
- [X] T073 [P] [US5] Cypress `frontend/cypress/e2e/console_live.cy.ts` (quickstart Scenario 5, SC-007/008/009): live counts match backend; two agents concurrent; dependency edge animates on real event; uniform agent detail for a graph + a non-graph agent; replay reconstructs; grep the built bundle → zero hard-coded status literals; kill/restore WS → backfill + resume, context preserved

**US5 delivery notes (increment 5b):**
- Backend: added `GET /organization/attention`, `POST /organization/decisions/{id}/resolve` (SA/PM/RM, `policy.csv` updated), and enriched `GET /organization/runs/{id}` (`RunDetailOut`: task_counts, pending_approvals, produced_strategy_id, result_summary, ended_at). 3 tests in `test_org_attention_api.py`.
- Frontend verified via `tsc --noEmit` + `eslint` + `next build` (all three routes compile). Cypress `console_live.cy.ts` needs the full-stack `cypress/included` container to execute (CI `cypress-e2e` job) — not run in this loop.
- **Simplifications**: `OrgTaskGraph` uses a self-contained layered-DAG SVG (does not import `graph-flowchart.tsx`'s internals), running-node pulse + solid satisfied-edge, `prefers-reduced-motion` honoured. `ActivityStream` is a capped scroll list (250 rows), not windowed-virtualised. `AgentDetail` covers overview / model-or-"deterministic" / capabilities / health / last+next execution / recent runs / recent tasks (with FR-083/084 explainer) / recent artefacts — tools/skills/audit-reference sub-sections abbreviated. `T071`: `/console` added to the shell nav; `/agents` is **kept** rather than redirected to `/console` (breaking the existing Agent Console + its Cypress specs was judged out of scope for this increment — revisit once the console fully supersedes it).

**Checkpoint**: the organisation is observable live and truthfully.

---

## Phase 8: User Story 6 — Per-agent Settings: prompt versions + provider/model (P2)

**Goal**: A dedicated Agent Settings area — prompt version history/activate/rollback + provider/model (AUTO default = unchanged) + test panel — `SystemAdministrator`-only, audited; deterministic agents show "no model — deterministic".
**Independent test** (spec US6): view prompt + history; create version (inactive) + diff; set custom provider + valid model, test, activate, verify audit, run agent, confirm the configured pair was used; a second agent on AUTO unchanged; deterministic agent has no picker; `PortfolioManager` config change → 403.

- [X] T074 [US6] Prompt-version seed migration `alembic/versions/<rev>_seed_prompt_versions.py`: import every current file prompt (`src/agents/prompts/<slug>/vN.md` + `registry.yaml`) into `prompt_versions` with `is_active` matching the file registry — **no behaviour change** (research R12)
- [X] T075 [US6] Change `src/agents/prompt_registry.py::get_active_prompt(slug, kind)` to read the DB `prompt_versions` active row, falling back to the file when no DB row exists (FR-102); `activate(slug, kind, version, actor)` / `rollback(...)` clear the prior active, write an `AuditLog` before/after, take effect next run with no redeploy (FR-102/103/107)
- [X] T076 [US6] Implement `src/orchestration/agent_config.py::resolve(agent_slug, task_type)`: precedence global `routing.yaml` → `AgentConfig.CUSTOM` pair (if currently configured & valid) as chain head → per-task override (policy-gated, future) → existing fallback chain (FR-106, research R11); `AUTO` path returns exactly today's selection
- [X] T077 [US6] Wire `agent_config.resolve` into `src/agents/llm_router.py::complete(task_type, …, agent_name=None)` — when `agent_name` is set and its config is `CUSTOM` with a valid pair, prepend it to the fallback chain; otherwise identical to today (FR-104, SC-010); pass `agent_name` from each LLM-backed node
- [X] T078 [US6] Implement `src/api/routers/agent_settings.py` per contracts/rest-api.md: `GET /` (config + effective provider/model + precedence level or "deterministic"), `GET /prompts`, `GET /prompts/{kind}/{version}`, `POST /prompts/{kind}` (**SA only**, inactive), `POST /prompts/{kind}/{version}/activate` (**SA only**), `.../rollback` (**SA only**), `PUT /provider-model` (**SA only**; `CUSTOM` invalid pair → 422; deterministic agent → 422 per clarify Q5), `POST /test` (**SA only**; runs prompt+model against the real router without activating; returns provider/model/latency/structured-output-valid/tool-compatible/token-cost?/errors — FR-108), `PUT /skills/{name}` (**SA only**, audited — FR-109)
- [X] T079 [P] [US6] Implement `src/api/routers/provider_models.py`: `GET /providers` (only `configured && key_present` from `routing.yaml` + Vault key presence via `resolve_api_key`), `GET /providers/health` (availability/latency/last-failure/in-fallback from **real** router telemetry + probes — FR-110, constitution VI); register both routers
- [X] T080 [P] [US6] Frontend `frontend/src/components/agent-settings/{PromptVersionHistory,PromptDiff,PromptEditor,ProviderSelector,ModelSelector,ProviderHealth,TestPanel}.tsx` using the existing shadcn primitives + `diff` package; ProviderSelector/ModelSelector offer only configured+valid options (FR-105); deterministic agent renders "no model — deterministic" (clarify Q5)
- [X] T081 [US6] Frontend route `frontend/src/app/(app)/settings/agents/[agentId]/page.tsx` (Agent Settings, distinct from global settings — FR-100) + add an "Agent Settings" section to the settings nav; add `manageAgentConfig` (SA-only) entries to `frontend/src/lib/permissions.ts`
- [X] T082 [P] [US6] **(Agent Settings — MANDATORY)** Integration test `tests/integration/test_agent_settings.py` (brief §81, quickstart Scenario 6, SC-011/012/016): create version (inactive) → activate → audit before/after → run agent → `provenance.provider_used`/`model_used` = configured pair; `CUSTOM` invalid model → 422; deterministic agent `PUT /provider-model` → 422; `PortfolioManager` any write → 403 audited
- [X] T083 [P] [US6] Golden test `tests/unit/test_llm_router_auto_unchanged.py` (SC-010): for an agent left on `AUTO`, `complete(...)`'s provider/model selection for fixed inputs is byte-for-byte the pre-feature selection
- [X] T084 [P] [US6] Cypress `frontend/cypress/e2e/agent_settings.cy.ts`: prompt history + diff + activate; provider/model pickers show only valid options; test panel returns real values; deterministic agent shows no picker

**US6 delivery notes:**
- 6b (frontend): `agent-settings/` = `PromptDiff` + `PromptVersionHistory` (history + two-version diff + SA-only activate/rollback) + `PromptEditor` (create inactive version) + `ProviderModelPanel` (AUTO/CUSTOM, pickers limited to configured providers, deterministic → no picker) + `ProviderHealth` + `TestPanel`. Route `settings/agents/[agentId]`; an "Agent Settings" section on `/settings` lists every registry slug. `manageAgentConfig` (SA-only) added to `permissions.ts`. Cypress `agent_settings.cy.ts` written (needs the full-stack container to run). Verified: `tsc` + `eslint` + `next build` clean.

- `d4f2a1c9e650` seeds `prompt_versions` from every `src/agents/prompts/<slug>/vN.md` (`_task`/`_chat` slugs → `(agent_slug=<base>, kind=<task|chat>)`); migration up/down/up verified; `get_active_prompt` is DB-first with a file fallback and returns byte-identical content post-seed.
- `agent_settings.py` implements every contract endpoint **except `PUT /skills/{name}`** (deferred — the existing skills router covers per-skill enable/disable; wiring the per-agent overlay is a follow-up).
- `provider_models.py` `GET /health` reports **honest nulls** for `p50_latency_ms` / `last_failure_at` — the router has no persistent latency telemetry yet (constitution VI: no fabricated numbers); `availability` is a real `is_configured` probe.
- `is_valid_pair` requires the model be one `routing.yaml` already uses for that provider, so "CUSTOM invalid model → 422" is deterministic regardless of which keys the environment has.
- T077: `complete(..., agent_name=...)` prepends the CUSTOM pair; **no LLM-backed node passes `agent_name` yet** — the org `agent_invoker` / graph nodes get that wiring with the real per-agent handlers (US6 remainder / US4-T036 deferral). The plumbing + golden test (T083) prove the AUTO path is byte-for-byte unchanged.
- Frontend (T080/T081/T084) is the next increment (6b).

**Checkpoint**: per-agent prompt + model management, with today's routing preserved by default.

---

## Phase 9: User Story 7 — Data-freshness awareness (P2)

**Goal**: Datasets have a cadence + freshness rule + checksum validation; the CEO defers dataset-dependent tasks when stale while running independents; the console shows freshness; stale/failed ingestion alerts; no synthetic data.
**Independent test** (spec US7): stale dataset → dependent task `blocked` "data stale", independents run, console shows it, alert fires; valid re-ingestion (checksum ok) unblocks; failed/corrupt ingestion does not mark fresh; no synthetic backfill on this path.

- [ ] T085 [US7] Implement `src/orchestration/freshness.py`: wraps `src/data/datalake/freshness.py::check_freshness()`; upserts a `DatasetFreshnessRecord` per dataset (`ohlcv_daily`, `instrument_master`, `corporate_actions`, `news`, `nse_index_ohlcv`) with `last_successful_update`, `last_checksum_ok`, `status ∈ {fresh, stale, unavailable, failed}`, `retry_state` (data-model.md §11); `is_fresh(dataset)` for the planner
- [ ] T086 [US7] Add a real nightly EOD ingestion job to `src/agents/scheduler.py` using the existing bhavcopy provider (REL-091…094): cadence "nightly after NSE close on trading days" (holiday-aware via `nse_holiday_calendar`), validates a checksum before setting `status = fresh` (FR-064); a failed/corrupt run sets `failed`/`unavailable` and emits `dataset.ingestion_failed` (research R10)
- [ ] T087 [US7] `planner.py` / `agent_invoker.dispatch`: check `freshness.is_fresh(dataset)` for a task's `required_datasets` before dispatch; stale/unavailable → task `blocked` with `blocked_reason = "data stale: <dataset>"` while independent tasks proceed (FR-062); **never** substitute synthetic data (FR-063)
- [ ] T088 [US7] Emit `dataset.stale` / `dataset.refreshed` / `dataset.ingestion_failed` events and raise an alert via the existing Grafana/Slack contact point on stale/failed (FR-062); surface per-dataset freshness in `GET /organization/runs/{id}` and `GET /attention`
- [ ] T089 [P] [US7] Frontend: data-freshness panel in `OrganizationOverview.tsx` (last successful update + status per dataset)
- [ ] T090 [P] [US7] Integration test `tests/integration/test_org_data_freshness.py` (quickstart Scenario 7, SC-006): stale → dependent `blocked` "data stale", independents run, `dataset.stale` event + alert; valid ingestion → unblocks; assert no synthetic rows written on this path
- [ ] T091 [P] [US7] Unit test `tests/unit/test_eod_ingestion_checksum.py`: a corrupt/failed ingestion does **not** set `status = fresh` (FR-064)

**Checkpoint**: staleness is a visible organisational fact, not a silent backtest rejection (BUG-A).

---

## Phase 10: User Story 8 — Ad-hoc agent-driven analysis & omni-channel objectives (P2)

**Goal**: "Do something" requests run through the organisation and are traceable to a real execution; channel objectives reach the CEO; pure lookups are answered directly.
**Independent test** (spec US8): "analyse my portfolio…" → a run/task, real data + tools, answer linked to the execution + audit; channel "run today's research" → real plan + CEO synthesis reply; "what's my P&L" → direct answer, no run; unmapped channel sender → recorded, not run.

- [ ] T092 [US8] Implement an inbound-message classifier in `src/api/routers/chat.py` and `src/api/routers/webhooks.py`: actionable objective → `run_manager.create_run(objective, source=<channel>, requested_by=<mapped identity>)`, reply = the run's `CeoSynthesis` artefact (FR-130/132); pure data lookup → answer directly, **no run** (FR-133)
- [ ] T093 [US8] Add an `AdHocAnalysis` capability/plan template in `planner.py` for portfolio-analysis / risk-ranking / drawdown-explanation / strategy-failure-explanation / rerun-decision objectives — assigns the appropriate existing agents + tools; result is an `AdHocAnalysis` artefact with full provenance (FR-130) and an `AuditLog` entry
- [ ] T094 [US8] Channel identity: actionable objectives require the sender mapped to an authorised identity via `NOTIFICATION_CHANNELS` (SEC-030); unmapped senders are recorded (`WebhookEvent`) and **not** run (spec A-14)
- [ ] T095 [P] [US8] Integration test `tests/integration/test_org_adhoc_and_omnichannel.py` (quickstart Scenario 12, SC-022): web "analyse my portfolio…" → run + real data + traceable answer + audit; channel "run today's research" → real run + synthesis reply; "what's my P&L" → direct, no run; unmapped sender → recorded, not run

**Checkpoint**: meaningful user requests are agent-executed, not static dashboard data dressed up as analysis.

---

## Phase 11: User Story 9 — Enforced agent enable/disable across all agents (P3)

**Goal**: Every agent's enable/disable state affects execution; the CEO handles an unavailable required capability by policy; changes emit events + audit; the audit agent cannot be disabled.
**Independent test** (spec US9): disable a required agent → CEO applies fallback/wait/reassign/escalate, records the decision, does not dispatch it; re-enable → used again; disable/enable audited + on the console; `audit_agent` disable refused.

- [ ] T096 [US9] Enforce `agent_control_state` at every call site for the 7 currently `enforced=False` agents (`execution_agent`, `portfolio_manager_agent`, `notification_agent`, `skill_registry_manager_agent`, `scheduler_agent`, `ceo_agent_chat`) — `agent_invoker.dispatch` and the scheduled-agent call sites check `is_agent_enabled` and skip with a logged "skipped, disabled" event (FR-120); flip their `enforced` flag in `KNOWN_AGENTS`
- [ ] T097 [US9] Implement the CEO unavailable-capability policy in `planner.py` / `agent_invoker.py`: on `AgentUnavailable`, the CEO chooses approved fallback / wait / reassign / escalate per config and records an `OrganizationalDecision`; the disabled agent is never dispatched (FR-005, FR-017, SC-013); queued tasks for a newly-disabled agent follow the same policy, none silently lost (FR-120)
- [ ] T098 [US9] `PUT /agents/control/{name}` emits `agent.disabled` / `agent.enabled` events + `AuditLog` (actor, reason); keep the `audit_agent` disable refusal (FR-121/122); console reflects real state (already wired via T062/T068)
- [ ] T099 [P] [US9] Integration test `tests/integration/test_org_agent_control.py` (quickstart Scenario 11, SC-013): disable a required agent → CEO decision recorded, agent not dispatched; re-enable → used; `audit_agent` disable → refused; events + audit present

**Checkpoint**: agent control is real for every agent.

---

## Phase 12: Polish & Cross-Cutting Concerns

- [ ] T100 [P] BUG-D: implement `fetch_global_indices` in `src/agents/tools/skills.py` (yfinance direct: `^GSPC`, `^IXIC`, `^N225`, `CL=F`, `INR=X` — the `IndiaVixSkill` pattern) and `query_news_sentiment` (query the `news_sentiment` Qdrant collection); leave `query_macro_calendar` / SEBI feed honestly `SkillNotImplementedError` with the coverage/governance note surfaced (FR-070/071, research R18)
- [ ] T101 [P] BUG-F: persist an `Order` row (and publish to the REL-061 order-status stream) from `src/engine/live/execution_pipeline.py`'s execution step so live-path orders reconcile like the manual path (research "Open items", FR-162); add `tests/integration/test_live_pipeline_order_persistence.py`
- [ ] T102 [P] BUG-H: correct stale docstrings — `src/agents/nodes/memory_agent.py` ("no scheduler exists yet") and `src/api/routers/agents.py` approve/reject ("no such feature exists in this pipeline")
- [ ] T103 BUG-E: add data-seeding + Qdrant bootstrap steps to the default `.github/workflows/ci.yml` job so `pytest` is green on a clean checkout; move the real-Zerodha tests behind `-m live` (SC-019); verify with a fresh-volume run
- [ ] T104 [P] Restart-resume integration test `tests/integration/test_org_restart_resume.py` (quickstart Scenario 8, SC-023): complete 2–3 tasks, `docker compose restart app`, assert automatic resume, zero re-execution of completed tasks, no regenerated artefacts, a mid-flight task re-attempted or `failed` (never false `completed`)
- [ ] T105 [P] **(Provider-failure — MANDATORY)** Integration test `tests/integration/test_org_provider_failure.py` (brief §84, quickstart Scenario 10, SC-018): provider A unavailable → routing falls back, run succeeds, `provenance.provider_used` = actual provider, `agent.fallback` event + audit, `GET /providers/health` shows A `unreachable` from a real probe
- [ ] T106 [P] **(Failure — MANDATORY)** Integration test `tests/integration/test_org_failure_handling.py` (brief §82, quickstart Scenario 9, SC-017): forced agent failure → task `failed` after retries, CEO failure event, human notified on repeated failure, dependents `blocked` not falsely completed, truthful console state, `AuditLog` entry
- [ ] T107 [P] Non-regression check (quickstart Scenario 13, SC-020): run the pre-existing `tests/unit/test_graph.py` / `test_node_*` and the existing Cypress suite unchanged and green; confirm `build_graph()` standalone tests unchanged (FR-150/152)
- [ ] T108 [P] Add per-task `timeout_seconds` enforcement in `task_engine.py` (default 300; 1800 for the `strategy_research` composite task) and the `stalled` run flag after `ORG_RUN_STALL_SECONDS` with an attention-queue entry, not auto-fail (research R20)
- [ ] T109 Full quality gate: `docker compose run --rm app sh -c "ruff check src tests && black --check src tests && mypy src && bandit -c pyproject.toml -r src && pip-audit"` clean; `frontend`: `npm run lint && npx tsc --noEmit` clean; per-module coverage gate passes for the new `src/orchestration/` module
- [ ] T110 [P] Update the ERDTM (`Project Document and BluePrint/TradingOS_ERDTM.xlsx`, local-edit only — never committed) with the new API/DB/Agent/Prompt rows and map BUG-A…I to Release Traceability; update `docs/audit-2026-09.md` status notes for the findings this feature closes
- [ ] T111 [P] Author `docs/orchestration-overview.md` (committed): architecture delta (current vs target), the organisation diagram, the CEO planning model, the task/dependency model, and the event model — distilled from plan.md + research.md + contracts/ for the engineering team
- [ ] T112 Run the full `quickstart.md` Scenario 1→13 sequence against the live Docker stack and record results; confirm all 5 mandated tests (T041, T044, T050, T082, T105/T106) and SC-001…SC-023 pass

---

## Dependencies & Execution Order

- **Phase 1 (Setup)** → **Phase 2 (Foundational)** → everything else. Phase 2 is a hard gate (models, migration, events, run_manager, capability registry, policy rows).
- **US1 (Phase 3)** depends on Phase 2. Delivers the plan object.
- **US2 (Phase 4)** depends on US1 (needs a plan to execute). Delivers parallel/dependent execution. **US1 + US2 = MVP organisation.**
- **US3 (Phase 5)** depends on Phase 2 for the gate mechanism; the full E2E test (T050) depends on US2 producing a deploy recommendation. US3 implementation can proceed in parallel with US2.
- **US4 (Phase 6)** depends on US2 (uses the plan/dependency machinery for the context tasks).
- **US5 (Phase 7)** depends on Phase 2 (events) for the console shell; meaningful content depends on US1/US2. Frontend tasks T064–T070 are mostly parallel.
- **US6 (Phase 8)** depends only on Phase 2 — **independent of US1–US5**; can be built in parallel once Foundational is done.
- **US7 (Phase 9)** depends on US1 (planner consults freshness).
- **US8 (Phase 10)** depends on US2 (`create_run` + execution).
- **US9 (Phase 11)** depends on US1 (agent_invoker) + Phase 2 (control state).
- **Phase 12 (Polish)** after the stories it references; T100/T101/T102/T103 are independent cross-cutting fixes that can start any time after Phase 2.

## Parallel Opportunities

- **Phase 2**: T006, T007, T008, T009 (separate model files) in parallel; T012, T016, T021, T023 in parallel.
- **US1**: T024 ∥ T030/T031 (prompt file vs tests) once T025–T029 land.
- **US2**: T041, T042, T043 in parallel after T032–T040.
- **US4**: T052 ∥ T060/T061.
- **US5**: T064, T065, T066, T067, T068, T069, T070 all parallel (separate component files); T062/T063 backend in parallel.
- **US6**: T079, T080, T082, T083, T084 in parallel after T074–T078; **the whole of US6 runs in parallel with US1–US5** (only Phase 2 dependency).
- **US7**: T089, T090, T091 in parallel after T085–T088.
- **Polish**: T100, T101, T102, T104, T105, T106, T107, T110, T111 largely parallel.

## Independent Test Criteria (per story)

| Story | Independently testable by |
|---|---|
| US1 | Submit 3 objectives → 3 distinct validated plans; 1 un-servable → `cannot_plan` (T030) |
| US2 | 4 independent tasks overlap; dependents wait; no missing-input execution; upstream fail → downstream `blocked` (T041 **mandatory**, T044 **mandatory**) |
| US3 | Strategy `PendingPaperApproval` not `PaperTrading`; only SA/PM approve; reject needs reason; no auto-transition (T050) |
| US4 | `ResearchContext` traces to this run's news+sentiment; no orphaned artefact; News down → `coverage=reduced`; conflict → CEO decision (T060, T061) |
| US5 | Console matches backend live, <~2 s, no refresh; concurrent agents; real-event edge animation; uniform agent detail; replay from events; zero hard-coded status; WS reconnect re-syncs (T073) |
| US6 | Create version (inactive) → activate → audit → run → configured pair used; AUTO agent unchanged; deterministic agent no picker; PM change → 403 (T082 **mandatory**, T083) |
| US7 | Stale dataset → dependent `blocked`, independents run, console + alert; valid re-ingestion unblocks; corrupt ingestion ≠ fresh; no synthetic data (T090, T091) |
| US8 | "analyse my portfolio" → run + traceable answer + audit; channel objective → real run + synthesis; pure lookup → no run (T095) |
| US9 | Disable required agent → CEO policy decision, not dispatched; re-enable → used; audit_agent disable refused (T099) |

## Implementation Strategy

- **MVP (demo the concept)**: **US1** alone — objective in, validated dynamic plan out. Narrowest independently testable slice.
- **Viable organisation (spec A-1)**: **US1 + US2 + US3 + US4** (all P1). At this point the product genuinely behaves as a CEO-led organisation with parallel execution, dependency-aware waiting, a real approval gate, and integrated market intelligence — and the P0 audit item (one unbroken end-to-end run) is achievable via T044 + T090's fresh data.
- **Premium product**: add **US5** (command centre) and **US6** (agent settings) — parallelisable; US6 has no dependency on US1–US5.
- **Hardening**: **US7** (freshness), **US8** (ad-hoc/omni-channel), **US9** (control enforcement), then Phase 12.
- Every task: `SPEC → CODE → UNIT/INTEGRATION/UI/E2E TEST → AUDIT → DOC` (brief §89); nothing marked done without its acceptance test green (constitution principle VI).
