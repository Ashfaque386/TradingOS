# Orchestration Layer Overview

**Feature**: `001-ceo-led-trading-org` | **Audience**: engineering team | **Status**: US1–US9 delivered (see `specs/001-ceo-led-trading-org/tasks.md` for per-task delivery notes, including partial/deferred scope)

This is a distilled architecture reference for the CEO-led organisation layer added under `src/orchestration/`. For the full design record see `specs/001-ceo-led-trading-org/{plan,research,data-model}.md` and `contracts/{rest-api,events,websocket}.md` — this document summarises and reflects the **as-built** state, which has diverged in some places from the original plan (noted inline).

## 1. Architecture delta: before → after

**Before** (audited system): the CEO agent emitted one `ResearchDirective` that a fixed 13-node LangGraph pipeline consumed linearly (Market Analyst → Strategy Generator → Code Gen → Validator → …). News/Sentiment/Portfolio agents ran on their own schedules but fed nothing back into that pipeline. Human approval was a post-hoc UI action with no real gate. Agent enable/disable was stored but not enforced. There was no general task queue, no dependency model, and no way for the CEO to delegate independent work in parallel.

**After**: a new `src/orchestration/` module sits *above* the existing pipeline and *reuses* it rather than replacing it:

```text
User objective (web / schedule / Telegram / Discord / Slack)
        │
        ▼
run_manager.create_run()  ──────────────►  OrganizationRun (queued|planning|running|waiting|stalled|completed|failed|cannot_plan|cancelled)
        │
        ▼
planner.generate_plan()  ── real LLM call, "orchestration" task type
        │  produces + deterministically validates an OrganizationalPlan
        ▼
task_engine.run_scheduler_loop()
        │  claims ready tasks (Postgres advisory lock), runs concurrency-safe
        │  ones on a bounded ThreadPoolExecutor, serialises the rest
        ▼
agent_invoker.dispatch()  ── capability → real handler (or an honest placeholder)
        │  market_analysis / news_ingestion / sentiment_analysis / portfolio_read /
        │  context_assembly / synthesize / adhoc_synthesis are real;
        │  strategy_research still runs a placeholder (see §6)
        ▼
ResultArtefact (typed, provenance-stamped)  ──►  dependency_resolver marks dependents ready
        │
        ▼
decisions.py (conflict detection / CEO decisions)  ──►  events.py (Postgres + Redis + audit)
        │
        ▼
Organization Command Center (console/) — reads the same rows, never a second truth
```

The existing `build_graph()` research pipeline, LLM router, SkillRegistry, sandbox, deterministic risk/compliance engines, Qdrant, Redis, and Postgres are all reused as-is — no datastore or safety control was replaced (constitution principles II/IV/V).

## 2. The CEO planning model

`planner.generate_plan(session, run)`:

1. Queries `organization_memory` (Qdrant) for similar past plans/lessons.
2. Calls the LLM (`llm_router.complete("orchestration", ...)`) with the current capability snapshot (`capability_registry.snapshot()` — every known agent, its department, capabilities, and live `enabled`/health state) and the objective.
3. Parses a strict `OrganizationalPlan` (tasks, `assigned_agent` by capability, `dependencies`, `priority`, `expected_output`, `constraints`, `safety_requirements`, `approval_required`).
4. **Deterministic, non-LLM validation** (`validate_plan`): the task/dependency graph must be acyclic, every `assigned_agent` must exist and declare the claimed capability, every dependency must target an in-plan task, and any safety-ordered stage present (`code_validation → compliance_check → backtesting → strategy_evaluation → risk_assessment`) must appear in that relative order. Bounded retry (3 attempts) with the validation error fed back to the LLM; on exhaustion the run is marked `cannot_plan` with a recorded `OrganizationalDecision` — never a fabricated plan.
5. `ensure_research_scaffold()` / `ensure_adhoc_scaffold()` deterministically add the context-gathering tasks (`news_ingestion`, `sentiment_analysis`, `portfolio_read`, `market_analysis`, `data_freshness`, `context_assembly`) whenever the plan contains a strategy-generating or ad-hoc-analysis capability — the LLM decides *what* to research, the scaffold guarantees *how* it's wired together.

The CEO never executes specialist work itself; it delegates by capability, not by hard-coded agent ID (`capability_registry.find_by_capability`), so a new agent declaring an existing capability slots in without planner changes.

## 3. The task / dependency model

Three lifecycle concepts are kept strictly distinct (a recurring audit finding, closed by design — FR-012):

| Concept | Enum | Lives on |
|---|---|---|
| Task status | `planned → ready → running → completed / failed / blocked / retrying / escalated / cancelled / superseded`, plus `waiting_for_dependency` / `waiting_for_agent` | `Task.status` |
| Run status | `queued → planning → running → waiting → stalled → completed / failed / cannot_plan / cancelled` | `OrganizationRun.status` |
| Approval status | `pending → approved / rejected` | `ApprovalRequest.status` |
| Agent status | enabled/disabled (US9) | `AgentControlState` |

**Claiming** (`task_engine._execute_task`): `UPDATE tasks SET status='running' WHERE id=:id AND status='ready'` inside a transaction holding `pg_advisory_xact_lock(hashtext('task:'||id))` — two workers racing the same ready task can never both win (`tests/unit/test_task_claim_race.py`).

**Concurrency**: only capabilities in the reviewed `CONCURRENCY_SAFE_CAPABILITIES` allowlist (`market_analysis`, `news_ingestion`, `sentiment_analysis`, `portfolio_read`, `data_freshness`, `memory_ingestion`, …) run in parallel on the bounded `ThreadPoolExecutor(ORG_TASK_POOL_SIZE)`; everything else — anything touching the kill-switch singleton, the shared sandbox pool, a broker write, or an Alembic-guarded table — serialises (spec Assumption A-8).

**Timeouts** (T108): every task gets a real `timeout_seconds` (default 300s; 1800s for the composite `strategy_research` task), enforced by running `agent_invoker.dispatch` in its own single-worker executor and bounding the wait with `future.result(timeout=...)`. A timeout skips the normal bounded-retry ladder (same reasoning as a stale-data block: a task that hangs once is likely to hang again) and is declared `failed` via a conditional `UPDATE ... WHERE status='running'`, so an orphaned dispatch call that finishes late can never resurrect an already-failed task.

**Stalled-run detection** (T108): `run_scheduler_loop` is synchronous and returns as soon as nothing is ready — it does not poll. A run that will never become ready again (nothing left to trigger it) would otherwise sit in `waiting` forever with nothing re-checking it. `task_engine.check_stalled_runs()`, run every 5 minutes by the `scheduler_stalled_run_sweep` cron job, flags such a run `stalled` after `ORG_RUN_STALL_SECONDS` (default 900s) with no pending approval — an attention-queue entry, never an auto-fail.

**Restart resume** (T104): `run_manager.reap_incomplete_runs()` (the FastAPI startup hook) resets a mid-flight `running` task to `ready` (if concurrency-safe) or `failed` (if not — never a false `completed`), then spawns one detached thread per reaped run to actually re-enter `_plan_run` or `run_scheduler_loop`, so the run genuinely continues rather than sitting idle with patched-up rows.

## 4. Agent dispatch: real vs. placeholder handlers

`agent_invoker.CAPABILITY_HANDLERS` is the single seam between a task's `capability` and the code that actually does the work:

| Capability | Handler | Real since |
|---|---|---|
| `synthesize` / `orchestrate` | real LLM call, CEO synthesis | US2 |
| `context_assembly` | assembles `ResearchContext` from this run's own artefacts | US4 |
| `adhoc_synthesis` | real LLM call answering an ad-hoc objective | US8 |
| `market_analysis` | real, standalone `market_analyst_node` call | T113 (Polish) |
| `news_ingestion` / `sentiment_analysis` | real reads of the `news_sentiment` Qdrant collection the scheduled `run_news_sentiment_cycle` job populates | T113 (Polish) |
| `portfolio_read` | real `portfolio_positions` query for the seeded Paper account | T113 (Polish) |
| `strategy_research` (composite) | **honest placeholder** — see §6 | — |
| anything else | honest, typed placeholder artefact (`_placeholder_handler`) | — |

Every real LLM-backed handler routes through `agent_invoker._record_llm_provenance()` (T105), which reads the actual `(provider, model, fell_back)` the LLM router just used (`llm_router.pop_last_call_info()`) so `ResultArtefact.provenance.provider_used`/`model_used` name the real provider — never a generic label — and emits a real, audited `agent.fallback` event when the chain had to route around a failed provider.

## 5. The event model

Every organisational state change is (a) an append-only `organizational_events` row (`(run_id, sequence)` unique, gap-free), (b) published to Redis channel `organization:events` for the console's live view, and (c) for the *meaningful-action* subset, an `AuditLog` hash-chain entry. See `contracts/events.md` for the full catalogue (`organization.run.*`, `task.*`, `dependency.*`, `result.*`, `agent.*`, `review.*`, `ceo.*`, `approval.*`, `dataset.*`). The console and run-replay view both read these same rows, so they cannot diverge from real state (FR-089/141).

Two additions beyond the original contract, both closing real gaps found during the Polish phase:

- `agent.fallback`'s actual payload is `{failed_providers: [...], provider_used, model_used}` (T105) rather than the contract's originally-sketched `{agent, from, to, reason}` shape — the real implementation needed to name *every* failed provider in the chain, not just one `from`.
- `organization.run.stalled` (already in the catalogue) is now actually emitted — nothing wrote it before T108.

## 6. Known deferral: `strategy_research`

The composite `strategy_research` capability — which should run the full `build_graph()` sub-graph (Market Analyst → Strategy Generator → Code Gen → Validator → Backtest → Evaluate → Risk, the safety-ordered chain constitution IV protects) as one task — is **still an honest placeholder**, tracked as **T113b**. This is the single largest piece of real per-agent-handler wiring left. It is not a small task: it needs `_execute_graph_run` extended with an optional `research_context` parameter (the state field already exists, `strategy_generator_node` already reads it — only the runtime population is missing), a decision on how the task engine's own timeout/cancel semantics interact with the graph's existing pause/resume/checkpointer model, and a way to read back the graph's terminal state (via `AgentRun.graph_thread_id`) as the task's result artefact. Until it lands, an organisation plan that reaches strategy generation produces a clearly-labelled placeholder artefact rather than a fabricated one — never a silent gap.

## 7. Safety invariants (unchanged, still enforced)

- The deterministic risk engine, kill switch, compliance checks, RBAC, and the immutable audit chain are strictly *above* the orchestration layer — the CEO planner can only sequence tasks *around* the safety-ordered chain, never reorder or bypass it (FR-050/051, constitution IV). `validate_plan` enforces this at plan-acceptance time; `test_org_planner.py`/`test_plan_validation.py` assert it.
- No code path the orchestration layer added places a live order automatically (FR-056). The one live order-placing path this Polish phase touched (`LiveExecutionPipeline`, T101) gained real persistence but no new trigger — it still has no production caller.
- Concurrency excludes the kill-switch singleton and the shared sandbox pool (spec A-8) — both stay serialised regardless of what else runs in parallel.
