# Phase 0 — Research & Architecture Decisions

**Feature**: CEO-Led AI Trading Organization | **Date**: 2026-09-10

All decisions honour: reuse-not-rewrite (spec A-6, FR-150), safety-control supremacy (FR-050/051, constitution IV), module storage ownership (constitution V), Docker-only (II), real-status honesty (VI). "Existing" = present in the codebase today per `docs/audit-2026-09.md`.

---

## R1. How the organisation layer relates to the existing LangGraph pipeline

- **Decision**: Add `src/orchestration/` as a layer *above* `src/agents/graph.py`. The existing compiled research graph (`build_graph()`, 13 nodes) stays and is invoked **as a single composite task** ("run strategy research sub-graph") by `agent_invoker.py`. Individual capabilities that the CEO may want to run *in parallel upstream of* that sub-graph (market analysis, news, sentiment, portfolio, data-freshness, risk-context) are also exposed as **standalone tasks** that call the same node functions / scheduled-agent functions directly. The safety-ordered inner chain (compliance → validator → backtesting → evaluator → risk → deployment) is **never decomposed for parallelism** — it runs only inside the composite sub-graph task, preserving FR-051 and constitution IV.
- **Rationale**: Zero rewrite of proven code; the graph's own retry loops, checkpointer, and safety veto edges are untouched. The CEO gains parallel fan-out for the *context-gathering* half of Workflow 1 (which the audit says is where News/Sentiment/Portfolio are stranded) without touching the *safety-critical* half.
- **Alternatives considered**: (a) Fully decompose all 13 nodes into independent tasks — rejected: re-implements LangGraph's edge logic, risks reordering safety stages, huge blast radius. (b) Replace LangGraph with a custom DAG runner — rejected by FR-150 and no evidence it is needed.

## R2. Task execution & concurrency without a new broker

- **Decision**: `task_engine.py` runs a per-run scheduler loop. Ready tasks (all dependencies satisfied, assigned agent available) are submitted to a bounded `concurrent.futures.ThreadPoolExecutor` (`ORG_TASK_POOL_SIZE`, default 8). Each task row is claimed with a Postgres `SELECT ... FOR UPDATE SKIP LOCKED` / advisory-lock pattern so parallel run workers never double-claim. Node functions are synchronous today, so threads (not asyncio) match the existing detached-thread execution model in `src/api/routers/agents.py::_execute_graph_run`.
- **Concurrency-safety allowlist**: only task types with no shared-mutable-state hazard run in parallel — market analyst, news, sentiment, portfolio-read, data-freshness, RAG lookups, CEO synthesis. **Serialised** (never concurrent, even across runs): anything touching the kill-switch singleton, the shared sandbox worker pool (`src/engine/sandbox/pool.py`), a broker write path, or an Alembic-guarded table. The allowlist is a named constant reviewed in code, per spec A-8.
- **Rationale**: Reuses Postgres + stdlib; no Celery/RQ/Temporal-for-everything (Temporal stays scoped to Monte Carlo). Advisory-lock claim is the standard safe pattern for a DB-row queue.
- **Alternatives considered**: Temporal for all orchestration — rejected: ADR 4 scoped Temporal narrowly, its compose service uses in-memory persistence, and it would duplicate LangGraph's role. Celery/RQ — rejected: new infra, new failure modes, no requirement.
- **Watch item (Constitution re-check)**: the advisory-lock claim must be covered by a concurrency test that starts two run workers against the same ready task and asserts exactly one executes it.

## R3. Durable state & restart resume (FR-019, SC-023)

- **Decision**: Every `OrganizationRun`, `Task`, `TaskDependency`, `ResultArtefact`, `OrganizationalDecision`, and `OrganizationalEvent` is a committed Postgres row before/after each state transition. On app startup a **run reaper** scans for runs in a non-terminal state: tasks marked `completed` keep their artefacts; a task left `running` at crash time is reset to `ready` (if its type is idempotent/safely re-runnable) or `failed` with reason (if not) — never left as a false `completed`. The composite research sub-graph task additionally resumes via the **existing LangGraph `PostgresSaver`** keyed by the run's `thread_id` (REL-060), so an interrupted sub-graph re-runs only its unfinished nodes.
- **Rationale**: Reuses the checkpointer that already exists; the row-per-transition model is what makes replay (FR-087) and resume the same underlying data.
- **Alternatives considered**: In-memory task state with a periodic snapshot — rejected: violates FR-019's "resume automatically", loses work on crash.

## R4. Concurrency cap & objective queue (FR-009)

- **Decision**: `run_manager.py` enforces `ORG_MAX_CONCURRENT_RUNS` (default 3). `create_run(objective, ...)` inserts an `OrganizationRun` row in `queued` state; a dispatcher promotes `queued → planning` whenever active runs < cap, oldest-first. Queue position is a real, queryable, console-visible field. A queued run is never merged or dropped.
- **Rationale**: Bounded contention on the single host's LLM budget and sandbox pool; ad-hoc analysis (US8) is not starved behind a long research run because the cap is >1.
- **Alternatives considered**: One-at-a-time (rejected by clarify Q3), unbounded (rejected: host resource exhaustion pattern documented in REL-008/009).

## R5. CEO planner: objective → Organizational Plan (FR-002…008)

- **Decision**: `planner.py` calls the LLM router `orchestration` task-type with a system prompt (`ceo_planner`, new PMPT entry) that is given the **capability registry snapshot** (agents, departments, capabilities, enabled/health, whether LLM-backed) and the objective, and must return a strict Pydantic `OrganizationalPlan` (tasks, per-task `assigned_agent` by capability, `dependencies` by task-id, `priority`, `expected_output` artefact type, `constraints`, `safety_requirements`, `approval_required`). The result is **validated deterministically**: graph must be acyclic (topological sort), every `assigned_agent` must exist and be capability-matched, every dependency target must exist, every safety-ordered stage that appears must appear in the mandated order. On validation failure the planner retries (bounded, with the error fed back); on exhaustion it emits a recorded `cannot_plan` outcome (FR-008), never a fabricated plan.
- **Rationale**: LLM does the judgement (which departments, what order), deterministic code enforces the invariants — mirrors the existing Evaluator pattern (LLM narrates, code decides). Capability-based assignment (FR-006) avoids hard-coded agent-id routing.
- **Alternatives considered**: Rule-based planner templates — rejected: the brief mandates *dynamic* planning; templates cannot cover arbitrary objectives. Fully free-form (no validation) — rejected by FR-007/008 and constitution IV.

## R6. Agent capability registry (FR-006, FR-016 registry fields)

- **Decision**: Extend `src/agents/control.py::KNOWN_AGENTS` (`AgentDescriptor`) with: `department`, `capabilities: tuple[str,...]`, `is_llm_backed: bool`, `concurrency_limit: int`, plus a runtime `health` derived from recent `AgentRun` outcomes + provider reachability. `capability_registry.py` serves this as the planner's snapshot and the console's directory. Departments: Executive, Market Intelligence, Research, Quant, Risk & Governance, Portfolio, Operations (spec FR-086).
- **Rationale**: One source of truth already exists (`KNOWN_AGENTS`); extend it rather than add a parallel registry. Health from real signals only (FR-110, constitution VI).
- **Alternatives considered**: New `agents` DB table — rejected: `KNOWN_AGENTS` is code-authoritative (an agent exists only if implemented); enable/disable state already lives in `agent_control_state`.

## R7. Structured collaboration & conflict resolution (FR-020…023)

- **Decision**: Delegation, hand-off, review request, review result, feedback, and escalation are rows in a single `organizational_decisions` / `task_events` structure (not free-text). `decisions.py` provides `detect_conflict(artefacts)` — a deterministic comparator for the known conflicting signal pairs (e.g. market regime vs aggregate sentiment sign; risk level vs proposed exposure). On conflict the CEO node is re-invoked with the conflicting artefacts and must produce an `OrganizationalDecision` (decision, reason, supporting inputs, next step) and, if the conflict severity crosses a threshold, an `escalation` to a human (visible in the approvals/attention queue). Peer review is invoked only where the plan's `safety_requirements` or a configured risk rule asks for it (FR-021) — not on every task.
- **Rationale**: Structured records make the console's Decision History and run replay real (FR-023, FR-087) and auditable (FR-142). Deterministic conflict detection avoids the LLM missing a disagreement.
- **Alternatives considered**: LLM-only conflict detection — rejected: unreliable; used as the *resolver*, not the *detector*.

## R8. Real HITL approval gate (FR-052…057, clarify Q1)

- **Decision**: The Deployment node stops writing `Strategy.status = "PaperTrading"`. Instead the run creates an `ApprovalRequest` row and sets the strategy to a new status **`PendingPaperApproval`** (new value in the strategy status enum + migration; deployment node / `_persist_strategy_progress` updated). `POST /organization/approvals/{id}/approve` (roles: `SystemAdministrator`, `PortfolioManager` only) performs the `PendingPaperApproval → PaperTrading` transition and writes the audit entry; `/reject` sets `Deprecated` with a mandatory reason. No timeout auto-approves (FR-057). Paper→Live is the untouched existing `/strategies/{id}/promote` gate (FR-055).
- **Rationale**: Minimal, bounded change that converts the audit's post-hoc annotation (BUG-B) into a real gate while matching the existing promote-gate authority (clarify Q1).
- **Alternatives considered**: Relabel the existing no-op "approve" as "acknowledge" — rejected: the spec (FR-052) requires the strategy *not* to enter Paper Trading before approval.

## R9. News / Sentiment / Portfolio integration (FR-040…044, BUG-C)

- **Decision**: The plan for a research objective includes parallel `news`, `sentiment` (depends on `news`), and `portfolio_read` tasks. A new `context_assembly` task (depends on market + news + sentiment + portfolio + risk-context as applicable) produces a **`ResearchContext` artefact** that the composite research sub-graph receives as an explicit input; `strategy_generator_node` is extended to read it (additive, behind the artefact being present — absent ⇒ current behaviour, so non-F&O/legacy paths unaffected). If a source is unavailable the `ResearchContext` carries `coverage: reduced` + which inputs are missing (FR-044). Portfolio artefact is recorded among the inputs to the relevant `OrganizationalDecision` (FR-043).
- **Rationale**: Wires the stranded agents in through the plan/dependency mechanism (the feature's own machinery) rather than a bespoke hook; honest reduced-coverage marker satisfies constitution VI.
- **Alternatives considered**: Push news/sentiment straight into `market_analyst_node` — rejected: hides the dependency, harder to show in the console, and couples two agents.

## R10. Data-freshness service & ingestion cadence (FR-060…064, BUG-A)

- **Decision**: `orchestration/freshness.py` wraps the existing `src/data/datalake/freshness.py::check_freshness()` and adds a per-dataset `DatasetFreshnessRecord` (last successful update, checksum result, status, cadence, retry state). The **scheduler gains a real recurring EOD ingestion job** using the existing bhavcopy provider (REL-091…094) so real data stops being ~2 years stale; ingestion validates a checksum before marking a dataset fresh (FR-064). The CEO planner queries freshness *before* dispatching a dataset-dependent task: stale ⇒ that task is `blocked` with reason "data stale" while independent tasks proceed (FR-062); the console shows per-dataset freshness (FR-062); stale/failed ingestion raises an alert via the existing Grafana/Slack path. No synthetic data is ever substituted (FR-063).
- **Rationale**: Reuses the freshness check and the bhavcopy provider that already exist; makes staleness a visible organisational fact instead of a silent backtest rejection.
- **Alternatives considered**: Auto-seed synthetic rolling data for demos — rejected by FR-063; acceptable only as an explicitly-labelled dev fixture outside the freshness path.
- **Deferred-from-clarify resolved here**: ingestion cadence = **once nightly after NSE close on trading days** (holiday-aware via `nse_holiday_calendar`); freshness threshold = **previous trading day's EOD present** (matches the existing Business Rule 4 semantics).

## R11. Provider / model override & precedence (FR-104…106, clarify Q4/Q5)

- **Decision**: New `AgentConfig` row per agent with `provider_model_mode` (`AUTO` | `CUSTOM`) and, when `CUSTOM`, `provider` + `model`. `src/agents/llm_router.py::complete(task_type, ..., agent_name=None)` gains an optional `agent_name`; when the agent's config is `CUSTOM` and the (provider, model) pair is currently configured & valid, it is used as the head of the fallback chain (the rest of the chain from `routing.yaml` still applies as fallback); otherwise behaviour is exactly today's. **Precedence** (FR-106): global default (`routing.yaml`) → agent default (`AgentConfig.CUSTOM`) → per-task override (only if a future task explicitly sets one and policy permits) → emergency/fallback routing (the existing chain). The console shows "using default routing" vs "custom model override active" from this resolution. **Deterministic agents** (validator, backtesting, compliance, data-ingestion, scheduler, audit — `is_llm_backed=False`) have no `provider_model_mode` and the Settings UI shows "no model — deterministic" (clarify Q5). Config changes are `SystemAdministrator`-only (clarify Q4) and audited with before/after (FR-107).
- **Rationale**: Additive to the router; `AUTO` path is untouched so SC-010 (byte-for-byte default) holds. Keys stay in Vault (`resolve_api_key`), only the *selection* is stored.
- **Alternatives considered**: Rewrite `routing.yaml` per agent — rejected: loses the global fallback semantics and the "AUTO = unchanged" guarantee.

## R12. Prompt version management (FR-101…103, US6)

- **Decision**: Introduce a `prompt_versions` table (agent_slug, version, kind [system|task], content, author, created_at, change_summary, is_active). `src/agents/prompt_registry.py::get_active_prompt(slug)` reads the DB active row, falling back to the existing file (`src/agents/prompts/<slug>/vN.md` + `registry.yaml`) if no DB row exists — so the current prompts seed the table on first migration and nothing changes until someone creates a new version. `activate` / `rollback` are `SystemAdministrator`-only, write an audit entry, and take effect on the agent's next run with no redeploy (FR-102). A new version is inactive until explicitly activated (FR-103). The test panel (FR-108) runs the prompt+model against the real router and reports provider/model/latency/structured-output-valid/errors without activating.
- **Rationale**: Preserves the file-based prompts as the seed + fallback (no behaviour change on day one), adds the dynamic surface the brief requires, keeps the audit trail.
- **Alternatives considered**: Keep editing files — rejected by FR-102 (no redeploy) and the audit's own finding.

## R13. Organisational memory (FR-032, FR-033)

- **Decision**: A new Qdrant collection **`organization_memory`** (same embedding provider config as the others) holding: past plans (objective + task shape + outcome), CEO decisions, conflict resolutions, rejected/failed strategy summaries, and lessons. `planner.py` and `decisions.py` query it (top-k) before planning / deciding. On a failed or rejected strategy the run writes a memory point (FR-033) — this also satisfies the existing `memory_ingest` node's intent at the organisation level. No new memory platform (constitution V; spec FR-032).
- **Rationale**: Reuses the Qdrant infra and embedding pipeline; a dedicated collection keeps organisational memory queryable without polluting `trading_strategies`.
- **Alternatives considered**: New payload class inside `trading_strategies` — viable but muddies that collection's schema and retrieval; rejected for clarity.

## R14. Event model, persistence & live fan-out (FR-140…142, US5)

- **Decision**: `OrganizationalEvent` rows (append-only, ordered by a per-run monotonic sequence + timestamp) are the single source for both live console updates and run replay. `events.py::emit(...)` writes the row, publishes a compact JSON payload to a new Redis channel `organization:events`, and — for meaningful actions — writes an `AuditLog` entry (reusing the existing hash-chain writer). The existing WS relay (`src/api/routers/streams.py`) gains an `/stream/organization` endpoint (or multiplexes on the existing agent stream) that relays that channel, filtered by run. Event catalogue is in `contracts/events.md`.
- **Rationale**: Row + channel + audit from one call keeps replay and live view consistent (they read the same rows); reuses the proven relay pattern.
- **Alternatives considered**: Postgres `LISTEN/NOTIFY` — viable but the Redis pub/sub + WS relay pattern already exists and is tested; no reason to add a second mechanism.

## R15. Frontend realtime & performance (FR-088, FR-172)

- **Decision**: One multiplexed WebSocket subscription per open console session (`useOrganizationStream`), keyed by selected run; React Query caches REST snapshots and the stream patches them. No polling where events exist (FR-172). Long lists (tasks, events, agents) use windowed rendering. The org task graph reuses the existing layered-DAG layout code from `graph-flowchart.tsx` (REL-033), extended for task nodes and dependency edges; animation is state-driven only (running pulse, dependency-edge activation, hand-off transition) per spec §32/§75. Reduced-motion respected (FR-170).
- **Rationale**: Reuses the DAG layout and WS hooks already in the codebase; avoids the duplicate-subscription and re-render pitfalls the spec calls out.
- **Alternatives considered**: Per-panel subscriptions — rejected by FR-172 (no duplicate subscriptions).

## R16. Status-concept separation (FR-012)

- **Decision**: Four distinct enums, never conflated: **RunStatus** {queued, planning, running, waiting, paused, completed, failed, cancelled}; **TaskStatus** {created, planned, queued, ready, running, waiting_for_dependency, waiting_for_agent, blocked, awaiting_approval, completed, failed, retrying, escalated, cancelled, superseded} (FR-011, BUG-I); **AgentStatus** {idle, running, escalated, disabled, degraded} (derived, not stored per-run); **ApprovalStatus** {pending, approved, rejected}. The console and API always label which one they show.
- **Rationale**: Directly closes BUG-I and FR-012; prevents the current ambiguity where "agent running" and "run running" are the same string.

## R17. Ad-hoc analysis & omni-channel routing (FR-130…134, US8, BUG "omni-channel trigger")

- **Decision**: `chat.py` and `webhooks.py` classify an inbound message: an **actionable objective** ("analyse my portfolio", "why did X draw down", "run today's research") calls `run_manager.create_run(objective, source=<channel>, requester=<mapped identity>)` and the reply is the CEO synthesis of that run; a **pure data lookup** ("what's my P&L") is answered directly without a run (FR-133). Actionable objectives from a channel require the sender to be mapped to an authorised identity (existing `NOTIFICATION_CHANNELS` mapping, SEC-030); unmapped senders are recorded, not run (spec A-14).
- **Rationale**: Reuses the identity mapping already built; routes real work through the same `create_run` path as the web app, so there is one orchestration entry point.
- **Alternatives considered**: A separate "analysis agent" outside the organisation — rejected: the spec wants agent-first *through the organisation*, and a second orchestration path would drift.

## R18. Missing skills (BUG-D, FR-070/071)

- **Decision**: Implement `fetch_global_indices` (yfinance: `^GSPC`, `^IXIC`, `^N225`, `CL=F`, `INR=X` — the same yfinance-direct pattern `IndiaVixSkill` already uses) and `query_news_sentiment` (query the existing `news_sentiment` Qdrant collection). Leave `query_macro_calendar` and any live SEBI feed **honestly unimplemented** — the skill raises the existing `SkillNotImplementedError` and the CEO/console surface the coverage gap and its governance implication (FR-071), never fabricated data.
- **Rationale**: Two are cheap real wins with sources that already work elsewhere in the codebase; the rest have no legitimate free source (confirmed in REL-016) and honesty is required by constitution VI.

## R19. Non-regression guarantees (FR-150…153, SC-010, SC-020)

- **Decision**: (a) `build_graph()` remains independently callable and its existing tests unchanged. (b) `llm_router.complete(...)` with no `agent_name` (or `AUTO` config) produces byte-for-byte the current provider/model selection — covered by a golden test (SC-010). (c) Existing dashboards/routes/tests keep passing; every intentional change ships with a test (SC-020). (d) The old `/agents` console route is kept as a redirect to `/console` (or folded in) so bookmarks survive. (e) BUG-G caption removed / derived from live topology; BUG-H docstrings corrected (`memory_agent.py`, `agents.py` approve/reject).
- **Rationale**: The audit is explicit that the foundation is real and must not regress; this makes it a testable gate.

## R20. Deferred performance items (from clarify)

- **Decision**: `Task.timeout` default = **300 s** per LLM-backed task, **1800 s** for the composite research sub-graph task (covers a cold sandbox ~20 s + backtest + optimisation), overridable per task type in config. An **organization run has no hard wall-clock cap**; instead a run with no task progress for `ORG_RUN_STALL_SECONDS` (default 900 s) is flagged `stalled` in the console and escalates to the attention queue — it is not auto-failed (matches FR-057's "no timeout auto-resolves" spirit for runs too). A per-LLM-call timeout (currently absent — audit AR-2) is added to `llm_router` to stop the zombie-thread pattern.
- **Rationale**: Concrete, configurable numbers derived from the real cold-start and backtest costs the audit measured; stall-flag rather than auto-fail keeps a slow-but-progressing run alive.

---

## Open items carried into design / tasks

| Item | Where resolved |
|---|---|
| Exact Postgres advisory-lock key scheme for task claim | data-model.md §Task + a concurrency integration test (quickstart §concurrency) |
| Whether `ApprovalRequest` is a new table or fields on an existing strategy-progress row | data-model.md §ApprovalRequest — **new table** (clean lifecycle, FK to Strategy + AgentRun) |
| `organization_memory` embedding dimension / bootstrap | matches `EMBEDDING_PROVIDER` config; bootstrapped by `src/memory/collections.py` extension |
| BUG-F: `LiveExecutionPipeline` Order persistence | cross-cutting task; persist an `Order` row + publish to the REL-061 stream from the pipeline execution step |
| BUG-E: CI green on clean checkout | cross-cutting task; add data-seeding + Qdrant bootstrap steps to the default job, quarantine broker-live tests behind `-m live` |
