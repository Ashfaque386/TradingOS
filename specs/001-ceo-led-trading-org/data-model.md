# Phase 1 — Data Model

**Feature**: CEO-Led AI Trading Organization | **Date**: 2026-09-10

Storage: **Postgres** (system of record) for every entity below, via new SQLAlchemy models under `src/models/` + Alembic migrations (run as the `tradingos` migration role; app runs as `tradingos_app`). Live event fan-out is Redis (ephemeral, not modelled here). Organisational memory is Qdrant (`organization_memory` collection, not modelled here). No new datastore (constitution V).

Conventions: UUID primary keys (`UUIDPKMixin`, matching existing models); `created_at` / `updated_at` timestamptz; JSONB for typed-artefact payloads and plan structures; `tenant_id` FK on run/task rows for forward-compatibility (spec A-13). All enums are Python `str` enums mirrored as Postgres `CHECK` constraints (matching `ml_models.model_type` precedent).

---

## Entity summary & relationships

```text
Tenant (existing) ──< OrganizationRun ──1─ OrganizationalPlan ──< Task ──< TaskDependency (self-ref via Task)
                          │                                        │
                          │                                        ├──< ResultArtefact ──(consumed_by)── Task
                          │                                        └──< TaskEvent
                          ├──< OrganizationalDecision ──(supporting_inputs)── ResultArtefact
                          ├──< OrganizationalEvent  (append-only, per-run sequence)
                          └──(produces)── Strategy (existing) ──1─ ApprovalRequest

Agent (KNOWN_AGENTS, code) ──1─ AgentConfig ──*─ PromptVersion
DatasetFreshnessRecord  (keyed by dataset name; referenced by Task.required_datasets)
ProviderModelConfig  (read-model over routing.yaml + Vault key presence + health signals — not a table)
```

Existing entities reused unchanged unless noted: `Strategy`, `StrategyVersion`, `BacktestResult`, `AgentRun`, `AgentLog`, `AgentControlState`, `AuditLog`, `Account`, `Order`, `Trade`, `NotificationChannel`, `Tenant`.

---

## 1. OrganizationRun

One execution of the organisation against one objective (spec: *Organization Run*).

| Field | Type | Notes |
|---|---|---|
| id | uuid PK | |
| tenant_id | uuid FK → tenants | |
| objective | text | plain-language objective as submitted |
| source | enum `web` \| `schedule` \| `telegram` \| `discord` \| `slack` \| `api` | FR-001, FR-132 |
| requested_by | text | authorised identity (user email or mapped channel identity); null for schedule |
| status | enum **RunStatus** | queued, planning, running, waiting, paused, stalled, completed, failed, cannot_plan, cancelled |
| queue_position | int null | set while `queued` (FR-009); null once promoted |
| plan_id | uuid FK → organizational_plans null | null until planning completes |
| thread_id | text unique | LangGraph checkpointer key for the composite research sub-graph task (FR-019) |
| result_summary | jsonb null | CEO synthesis handed back to the requester |
| produced_strategy_id | uuid FK → strategies null | set if the run produced a strategy |
| stall_flagged_at | timestamptz null | set when no task progress for `ORG_RUN_STALL_SECONDS` (research R20) |
| started_at / ended_at | timestamptz null | |
| created_at / updated_at | timestamptz | |

**Validation**: `status = cannot_plan` requires a recorded `OrganizationalDecision` with reason (FR-008). Only ≤ `ORG_MAX_CONCURRENT_RUNS` rows may be in {planning, running, waiting, stalled} at once (FR-009) — enforced in `run_manager`, asserted by a test.

**State transitions**: `queued → planning → running → (waiting ⇄ running) → completed | failed | cancelled`; `planning → cannot_plan`; any non-terminal `→ paused → running` (reuses existing pause/resume). On restart: non-terminal runs are re-entered by the reaper (FR-019).

---

## 2. OrganizationalPlan

The CEO's decomposition of an objective (spec: *Organizational Plan*).

| Field | Type | Notes |
|---|---|---|
| id | uuid PK | |
| run_id | uuid FK → organization_runs, unique | one plan per run (a re-plan supersedes via new plan + `superseded_plan_id`) |
| objective_classification | text | CEO's classification of the objective (e.g. `swing_research`, `portfolio_analysis`) |
| departments | jsonb (list[str]) | departments engaged (FR-002) |
| constraints | jsonb | plan-level constraints (universe, risk tolerance, deadline) |
| safety_requirements | jsonb | which safety-ordered stages / peer reviews the plan mandates (FR-021, FR-051) |
| approval_required | bool | whether the plan's outcome needs the HITL gate (default true for deploy-producing plans) |
| superseded_plan_id | uuid FK self null | set when the CEO re-plans mid-run |
| created_at | timestamptz | |

**Validation** (deterministic, `planner.py`, FR-007): the derived task/dependency graph MUST be acyclic; every task's `assigned_agent` MUST exist in the capability registry and match a declared capability; every dependency target MUST be a task in the same plan; any safety-ordered stage present MUST be in the mandated order.

---

## 3. Task

A unit of delegated work assigned to one agent (spec: *Task*; fields per FR-010).

| Field | Type | Notes |
|---|---|---|
| id | uuid PK | |
| plan_id | uuid FK → organizational_plans | |
| run_id | uuid FK → organization_runs | denormalised for query speed |
| parent_task_id | uuid FK self null | sub-tasks (e.g. partial-fill tracking) |
| tenant_id | uuid FK → tenants | |
| objective | text | |
| description | text null | |
| assigned_agent | text | agent `name` from `KNOWN_AGENTS` |
| assigned_by | text | `ceo_agent` or a human email (reassignment) |
| capability | text | the capability this task requires (FR-006) |
| priority | int | 1 = highest |
| dependency_policy | enum `all` \| `any` \| `best_effort` | how many dependencies must be satisfied (FR-010) |
| required_inputs | jsonb (list of artefact-type names) | FR-014 |
| received_inputs | jsonb (list of `{artefact_id, type}`) | populated as dependencies satisfy |
| required_datasets | jsonb (list[str]) null | dataset names checked against `DatasetFreshnessRecord` before dispatch (FR-061) |
| expected_output | text | artefact type name (e.g. `MarketContext`) |
| result_artefact_id | uuid FK → result_artefacts null | |
| status | enum **TaskStatus** | 15 values per FR-011 / research R16 |
| is_concurrency_safe | bool | from the reviewed allowlist (research R2, spec A-8) |
| retry_count / max_retries | int | default max 3 (matches graph loops) |
| timeout_seconds | int | default 300; 1800 for the composite research sub-graph task (research R20) |
| deadline | timestamptz null | |
| blocked_reason | text null | set when `blocked` (FR-017, FR-062) |
| failure_reason | text null | |
| correlation_id | text | = run `thread_id` for tracing |
| agent_run_id | uuid FK → agent_runs null | links to the existing per-node execution record |
| audit_reference | uuid FK → audit_log null | |
| created_at / started_at / completed_at | timestamptz null | FR-016 |
| ran_concurrently | bool | true if it overlapped a sibling in wall-clock (FR-016) |
| dependency_wait_seconds | int | total time in a waiting state (FR-016) |

**Claiming** (research R2): a worker claims a `ready` task with `UPDATE tasks SET status='running', started_at=now() WHERE id=:id AND status='ready' RETURNING *` inside a transaction holding `pg_advisory_xact_lock(hashtext('task:'||id))`; exactly one worker wins (concurrency test in quickstart).

**State transitions**:
`created → planned → queued → ready → running → completed`
`ready → waiting_for_dependency` (dep unmet) `→ ready` (dep satisfied event)
`ready → waiting_for_agent` (assigned agent busy/at concurrency limit) `→ ready`
`ready|running → blocked` (dependency can never be satisfied / dataset stale, FR-017/062) — terminal-ish, needs CEO decision to re-plan
`running → retrying → running` (bounded) `→ failed` (budget exhausted)
`running → escalated` (agent escalates to CEO)
any → `cancelled` (run cancelled); `→ superseded` (re-plan replaced this task)
composite-research task only: `running → awaiting_approval` is **not** used — the strategy's `ApprovalRequest` carries that; the task completes and the run enters `waiting` on the approval.

---

## 4. TaskDependency

A directed "task A requires an input owned by task B" edge (spec: *Task Dependency*).

| Field | Type | Notes |
|---|---|---|
| id | uuid PK | |
| plan_id | uuid FK → organizational_plans | |
| dependent_task_id | uuid FK → tasks | the waiter |
| prerequisite_task_id | uuid FK → tasks | the owner of the needed input |
| required_artefact_type | text | e.g. `NewsDigest` |
| policy | enum `hard` \| `soft` | soft = proceed with reduced coverage if unmet (FR-044) |
| state | enum `unsatisfied` \| `satisfied` \| `failed` | FR-015 |
| satisfied_at | timestamptz null | |

**Validation**: `(dependent_task_id, prerequisite_task_id)` unique; no self-edge; the full edge set per plan MUST be acyclic (checked at plan validation, FR-007). `state = failed` when the prerequisite task ends `failed`/`blocked` and there is no alternative producer ⇒ dependent task → `blocked` with reason (FR-017).

---

## 5. ResultArtefact

A typed output of an agent with provenance (spec: *Result Artefact*; FR-030/031).

| Field | Type | Notes |
|---|---|---|
| id | uuid PK | |
| run_id | uuid FK → organization_runs | |
| task_id | uuid FK → tasks | producer |
| artefact_type | text | one of the known types (ResearchDirective, MarketContext, NewsDigest, SentimentReport, PortfolioRiskReport, AllocationPlan, ResearchContext, StrategyLogic, OptionStrategyProposal, PythonCode, ValidationReport, ComplianceReport, BacktestMetrics, OptimizationReport, RiskReport, EvaluationReport, DeploymentRecommendation, CeoSynthesis, AdHocAnalysis) |
| version | int | increments if the same task re-produces |
| payload | jsonb | the typed content (validated against a Pydantic schema per `artefact_type`) |
| provenance | jsonb | `{agent, task_id, run_id, model_used, provider_used, tools_used[], inputs[], produced_at}` (FR-030) |
| disposition | enum `consumed` \| `informational` | FR-031 — every artefact must be one or the other; `consumed` requires ≥1 `TaskDependency` referencing it |
| consumed_by_task_ids | jsonb (list[uuid]) | populated when a downstream task ingests it |
| coverage | enum `full` \| `reduced` null | set on assembled context artefacts when a source was missing (FR-044) |
| audit_reference | uuid FK → audit_log null | |
| created_at | timestamptz | |

**Validation**: a run may not reach `completed` while any of its artefacts has `disposition = NULL` (SC-004). `payload` MUST validate against the schema registered for `artefact_type` (FR-030, "typed").

---

## 6. OrganizationalDecision

A CEO-level decision, including conflict resolution and escalation (spec: *Organizational Decision*; FR-022/023).

| Field | Type | Notes |
|---|---|---|
| id | uuid PK | |
| run_id | uuid FK → organization_runs | |
| decision_type | enum `proceed` \| `request_review` \| `resolve_conflict` \| `choose_fallback` \| `reassign` \| `escalate_human` \| `cannot_plan` \| `re_plan` | |
| summary | text | operational statement (no private chain-of-thought, FR-023) |
| reason | text | |
| supporting_input_artefact_ids | jsonb (list[uuid]) | FR-022, FR-043 |
| supporting_agents | jsonb (list[str]) | |
| next_step | text null | |
| escalated_to_role | text null | when `escalate_human` |
| resolved_by | text null | human email if a human resolved the escalation |
| audit_reference | uuid FK → audit_log | required (FR-142) |
| created_at | timestamptz | |

**Conflict detection** (`decisions.detect_conflict`, research R7): deterministic comparator over the artefact set for known opposing pairs (market regime vs sentiment sign; risk level vs proposed exposure; compliance block vs strategy proceed). A detected conflict MUST produce a `resolve_conflict` decision before the run continues (SC-014).

---

## 7. ApprovalRequest

A pending human decision on a deployment recommendation (spec: *Approval Request*; FR-052…057, clarify Q1).

| Field | Type | Notes |
|---|---|---|
| id | uuid PK | |
| run_id | uuid FK → organization_runs | |
| strategy_id | uuid FK → strategies | subject strategy (in status `PendingPaperApproval`) |
| strategy_version_id | uuid FK → strategy_versions null | |
| recommendation_artefact_id | uuid FK → result_artefacts | the `DeploymentRecommendation` |
| status | enum **ApprovalStatus** | pending \| approved \| rejected |
| decided_by | text null | user email (must hold `SystemAdministrator` or `PortfolioManager`) |
| decided_at | timestamptz null | |
| reason | text null | **required** when `status = rejected` (FR-053) |
| audit_reference | uuid FK → audit_log null | written on decision |
| created_at | timestamptz | |

**State transitions**: `pending → approved` (⇒ `Strategy.status: PendingPaperApproval → PaperTrading`, audit) or `pending → rejected` (⇒ `Strategy.status: PendingPaperApproval → Deprecated`, reason + audit). No timeout transition (FR-057). Only the two allowed roles may decide; any other actor ⇒ 403 + audited denial (FR-053).

**Strategy status enum change**: add `PendingPaperApproval` between the existing pre-Paper statuses and `PaperTrading` (migration; update `deployment_node` / `_persist_strategy_progress` to write `PendingPaperApproval` instead of `PaperTrading`, and the existing no-op `approve_run` is replaced by this real gate).

---

## 8. OrganizationalEvent

Immutable record of a real state transition; source for live updates + replay (spec: *Organizational Event*; FR-140/141, FR-087).

| Field | Type | Notes |
|---|---|---|
| id | uuid PK | |
| run_id | uuid FK → organization_runs | |
| sequence | bigint | per-run monotonic (gap-free); `(run_id, sequence)` unique |
| event_type | text | from the catalogue in `contracts/events.md` (plan.*, task.*, agent.*, dependency.*, result.*, review.*, approval.*, ceo.decision.*) |
| subject_type | text | `run` \| `plan` \| `task` \| `agent` \| `dependency` \| `artefact` \| `approval` \| `decision` |
| subject_id | uuid null | |
| payload | jsonb | compact, display-ready (FR-141) |
| occurred_at | timestamptz | |

**Rules**: append-only (DB trigger rejects UPDATE/DELETE, same pattern as `audit_log`); every emit also publishes to Redis `organization:events` and, for meaningful actions, writes an `AuditLog` row (FR-142). Replay = ordered read of these rows for a run (FR-087).

---

## 9. AgentConfig

Per-agent configuration overlay (spec: *Agent Configuration*; FR-100…110, clarify Q4/Q5).

| Field | Type | Notes |
|---|---|---|
| id | uuid PK | |
| agent_slug | text unique | agent `name` from `KNOWN_AGENTS` |
| is_llm_backed | bool | copied from the descriptor; deterministic agents = false |
| provider_model_mode | enum `AUTO` \| `CUSTOM` null | null for deterministic agents (no picker, FR-104 / clarify Q5); default `AUTO` for LLM agents |
| custom_provider | text null | only when `CUSTOM`; must be a currently-configured provider |
| custom_model | text null | only when `CUSTOM`; must be valid for `custom_provider` |
| active_system_prompt_version_id | uuid FK → prompt_versions null | null ⇒ fall back to file-based active prompt |
| active_task_prompt_version_id | uuid FK → prompt_versions null | same |
| updated_by | text | last `SystemAdministrator` to change it |
| updated_at | timestamptz | |

**Validation**: any write requires `SystemAdministrator` (clarify Q4) and writes an `AuditLog` entry with before/after (FR-107, SC-012). `CUSTOM` with an unconfigured/invalid pair is rejected at write time (FR-105); if it becomes invalid later, resolution falls back per precedence and the console shows the fallback (research R11, edge case).

**Resolution precedence** (FR-106, `agent_config.resolve(agent_slug, task_type)`): global `routing.yaml` chain → this row's `CUSTOM` pair as chain head (if valid) → per-task override (future, policy-gated) → existing fallback chain. `AUTO` ⇒ identical to today (SC-010).

---

## 10. PromptVersion

An immutable version of an agent's prompt (spec: *Prompt Version*; FR-101…103, FR-108).

| Field | Type | Notes |
|---|---|---|
| id | uuid PK | |
| agent_slug | text | |
| kind | enum `system` \| `task` | |
| version | int | `(agent_slug, kind, version)` unique |
| content | text | |
| author | text | user email |
| change_summary | text | |
| is_active | bool | at most one active per `(agent_slug, kind)` |
| created_at | timestamptz | |

**Seeding**: on first migration, the current file-based prompts (`src/agents/prompts/<slug>/vN.md` + `registry.yaml`) are imported as version rows with `is_active` matching the file registry — **no behaviour change** (research R12). `get_active_prompt(slug)` reads the DB active row, falling back to the file if no row exists.

**Transitions**: `create` (inactive) → `activate` (SA-only, audited, clears the previous active) → optional `rollback` (activate an older version; itself audited). Effective on the agent's next run, no redeploy (FR-102).

---

## 11. DatasetFreshnessRecord

Per required dataset (spec: *Dataset Freshness Record*; FR-060…064).

| Field | Type | Notes |
|---|---|---|
| id | uuid PK | |
| dataset_name | text unique | e.g. `ohlcv_daily`, `instrument_master`, `corporate_actions`, `news`, `nse_index_ohlcv` |
| cadence | text | e.g. `nightly_after_nse_close` (research R10) |
| freshness_rule | text | e.g. `prev_trading_day_eod_present` |
| status | enum `fresh` \| `stale` \| `unavailable` \| `failed` | |
| last_successful_update | timestamptz null | |
| last_checksum_ok | bool null | FR-064 |
| retry_state | jsonb | `{attempts, next_retry_at, last_error}` |
| updated_at | timestamptz | |

**Rules**: an ingestion run sets `status = fresh` only if the data passed checksum validation (FR-064); a failed/corrupt ingestion sets `failed`/`unavailable` and raises an alert (FR-062, FR-064). The planner reads this before dispatching a task whose `required_datasets` names it (FR-061); stale/unavailable ⇒ dependent task `blocked` with reason while independents proceed (FR-062). No synthetic backfill on this path (FR-063).

---

## 12. ProviderModelConfig (read-model, not a table)

A computed view (`provider_models.py`) over: `routing.yaml` (configured providers/models), Vault key presence (`resolve_api_key`), and recent success/latency/failure signals from `AgentRun` + router telemetry. Fields per provider/model: `configured`, `key_present`, `availability` (`connected` \| `degraded` \| `unreachable`), `p50_latency_ms`, `last_failure_at`, `in_fallback`. Drives the Settings pickers (only `configured && key_present` offered, FR-105) and the console default-vs-override / provider-health display (FR-110) — **real signals only, never fabricated** (constitution VI).

---

## Migration notes

- New tables: `organization_runs`, `organizational_plans`, `tasks`, `task_dependencies`, `result_artefacts`, `organizational_decisions`, `approval_requests`, `organizational_events`, `agent_configs`, `prompt_versions`, `dataset_freshness_records`.
- Altered: `strategies.status` CHECK constraint gains `PendingPaperApproval`; `agent_run` gains nothing (reused via FK).
- Append-only trigger on `organizational_events` (reuse the `audit_log` trigger pattern; `tradingos_app` has SELECT/INSERT only).
- All migrations run as `tradingos` (migration role); app connects as `tradingos_app` (REL-014).
- `src/memory/collections.py` extended to bootstrap the `organization_memory` Qdrant collection at the configured embedding dimension.
