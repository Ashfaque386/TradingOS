# TradingOS Agent Console / Organization — Implementation Audit & Hardening Report

**Date**: 2026-09-12
**Auditor role**: Principal Product Architect / AI Agent Platform Architect / Senior Full-Stack Engineer / QA Architect
**Scope**: Verify, end-to-end and at the code level, whether the shipped "CEO-Led AI Trading Organization" (`001-ceo-led-trading-org`, REL-095/096, 2026-09-10/11) actually delivers the 18 capabilities required of a real agent-operations console, using a supplied reference UI (`multi-agent-ai-console.zip`) as a visual/UX reference only.
**Status**: Analysis complete. No code has been changed as a result of this report. Follow-on spec kit: [`specs/002-agent-organization-hardening/`](../specs/002-agent-organization-hardening/).

> **Amendment — 2026-09-12 (later same day):** This report's original framing of the reference ZIP (§2, and the "informational — visual reference only" characterization used throughout) was **corrected** after explicit review: the reference ZIP is the *primary* UX/UI/interaction baseline for redesigning the console's presentation layer, not a four-pattern mood-board layered onto an unchanged information architecture. The Current-State Verification and Audit Gap Analysis below (§3–§4) are unaffected — they are evidence about backend/data wiring, independent of this framing question. §2's "Reference ZIP Analysis" and §7's Implementation Plan are superseded by the corrected, expanded versions in [`specs/002-agent-organization-hardening/spec.md`](../specs/002-agent-organization-hardening/spec.md) (its own "Scope Correction — 2026-09-12" and "Reference ZIP Analysis" sections) and [`plan.md`](../specs/002-agent-organization-hardening/plan.md), which add three new user stories (US12 Agent Fleet, US13 CEO Workspace, US14 Dependency graph interactivity) and expand US4/US5/US6. Treat this document as historical record of the initial audit pass; treat the spec kit as current.

---

## 0. Executive Summary

TradingOS shipped a real CEO-led multi-agent organization two days before this audit — not a mock, not a demo. A skeptical, code-and-test-level re-verification (four independent deep-dive passes, each required to quote actual source and name actual tests rather than trust docstrings, component names, or the prior audit's own "RESOLVED" annotations) confirms that the **core organizational mechanics are genuinely real**: dynamic per-objective planning, true concurrent dispatch with race-safe task claiming, real dependency wait/wake, automatic conflict detection between disagreeing agents, and a live WebSocket-driven console are all implemented and covered by tests that would fail if the behavior regressed to a fake.

However, this audit also found **eleven concrete gaps**, three of which the shipped system's own audit trail incorrectly marked as closed:

- **One live governance bypass**: a pre-existing, unrelated endpoint can move a strategy into Paper Trading with zero reference to the approval system that is supposed to be the sole gate for that transition — a rejected strategy can still be promoted.
- **One fully-built-but-inert feature**: per-agent provider/model override has a complete database, API, audit, and UI path, but no real agent invocation ever passes the information needed to apply it — the override changes nothing today.
- **One missing first-class concept**: agent-to-agent "handoffs," despite being explicitly required, do not exist as an inspectable entity — only as data an operator would have to infer from task ordering.
- **One materially incomplete UI surface**: the per-agent detail workspace — the single most-referenced requirement in the target product vision — renders real data for only 3 of the 12 required sections, and loses all run/task context on every navigation into it.
- Six smaller but real gaps: no Task Board, no self-explaining activity feed, hard-coded (rather than capability-based) delegation in one code path, a task-lifecycle enum with unreachable states, unenforced-but-cataloged skill grants, and three completeness items (prompt-activation confirmation, run-history pagination, audit-reference back-links).

None of this calls for rebuilding the organization layer. It calls for finishing eleven specific, already-scoped pieces of work on top of an otherwise sound foundation. The reference ZIP contributes visual language only (it is a 43-line, fully-mocked, backend-less demo) and is not treated as an architecture to emulate.

---

## 1. Methodology

Rather than accept the existing documentation's self-reported status, this audit ran **four independent, parallel, code-level verification passes**, each instructed to:

- Distrust docstrings, comments, component/file names, and any prior "RESOLVED" annotation as evidence of correctness.
- Read the actual implementation logic, not summaries of it.
- Locate and read the actual automated tests exercising each capability, quoting what they actually assert (not just their name/existence).
- Where a claim could not be verified from code+tests alone, say so explicitly rather than assume.
- Render one of four verdicts per capability: **FULLY WIRED** (real, end-to-end, test-covered), **PARTIALLY WIRED** (real logic exists but has a material gap), **STATIC/MOCK** (looks real, isn't), or **MISSING**.

The four passes covered: (A) CEO orchestration, task/dependency model, parallel execution, handoffs, conflict review, failure/retry; (B) realtime events, audit trail, and an independent re-verification of every "RESOLVED" claim in the prior audit (`docs/audit-2026-09.md`); (C) the frontend console, agent workspace, activity stream, run history, and analytics; (D) prompt management, provider/model routing, and skills/tools configuration — each tracing the *full round trip* from UI action through API through database through the next real agent invocation, not just confirming an endpoint exists.

A separate pass reverse-engineered the reference ZIP (`multi-agent-ai-console.zip`) file-by-file to establish what it actually is before any comparison was drawn.

---

## 2. Reference ZIP Analysis

**What it is**: a single-page Next.js 16 / React 19 / Tailwind v4 demo named "Nexus — Agent OS." The entire application is one 43-line `app/page.tsx` plus a layout, a global stylesheet, and one unused shadcn `Button` primitive. There is **no `components/` subfolder of substance, no API route, no state management library, no charting library, and no `setInterval`/`setTimeout` anywhere in the code**.

**Tech stack**: Next.js 16.3.3 App Router, React 19, TypeScript 5.7.3, Tailwind CSS v4 (OKLCH-token shadcn theme defined but never actually used — the page hardcodes literal dark colors instead), `lucide-react` icons, no framer-motion (motion is pure CSS keyframes), no charting library (progress bars are styled `<div>` widths).

**Routes**: one real route (`/`). "Pages" (Overview, Live runs, Agents, Knowledge, Automations, Settings, Help center) are simulated via a client-side `activeNav` string switch inside a single component. Four of the seven nav items render the exact same generic `SimplePage` placeholder.

**Data model**: none. No TypeScript `interface`/`type` for agents, tasks, runs, handoffs, or approvals exists anywhere — everything is an untyped inline array literal:

```ts
const agents = [
  { name: 'Orchestrator', role: 'Lead coordinator', model: 'Claude 4 Opus', color: '#a78bfa',
    status: 'Running', icon: BrainCircuit, task: 'Coordinating market intelligence brief',
    progress: 72, latency: '1.2s', calls: 48 },
  // ...three more, all static
]
const streams = [
  ['09:42:18', 'observe', 'Detected new market signal in fintech / pricing', 'cyan'],
  // ...four more static rows
]
```

**Is it real or mocked?** Every dynamic-looking element is mock: agent status/progress/latency/call-count, the "current thought" panel, the "execution path" step timeline (hardcoded `i < 3` for which steps show as done, regardless of which agent is selected), and the "Live"/"History" activity toggle (which just reverses the same five static rows — no new events ever arrive). The only genuinely real client-side logic is `useState`-driven nav-tab switching and agent-card selection. There is no approvals concept anywhere in this codebase. Every button besides nav/agent-select/pause is non-functional (no `onClick`).

**What is worth adopting** (visual/UX patterns only, folded into this report's User Story 4/5/6 and the spec kit's US4/US5/US6):

1. **Agent-color-as-identity** — one accent color per agent threaded through icon tint, status dot, progress bar, and active-card border/glow via a single CSS custom property.
2. **Tone-tagged event log** — a small set of semantic colors keyed to event-type keywords; directly adaptable to TradingOS's real `OrganizationalEvent.event_type` families (`plan.*`, `task.*`, `agent.*`, `dependency.*`, `result.*`, `review.*`, `approval.*`, `ceo.decision.*`).
3. **Two-panel "agent deep-dive + live log" layout** as an information-architecture shape.
4. **Vertical step-timeline** (checkmark vs. pending) for a task/run's execution path.

**What must not be copied**: any of its data (100% hardcoded fixtures), its `SimplePage` placeholder pattern, its non-functional buttons, its fake "CONNECTED"/pulsing-dot live-sync indicators (no real connection exists underneath them), and its practice of hardcoding literal dark colors instead of using the shadcn semantic tokens it ships but never uses (TradingOS's own frontend must keep proper light/dark token usage).

---

## 3. Current-State Verification (detailed, evidence-based)

Each capability below states the verdict, the concrete code evidence (file path + the actual logic), and the test coverage found — or its explicit absence.

### 3.1 CEO orchestration and delegation — **PARTIALLY WIRED**

`src/orchestration/planner.py::generate_plan` genuinely calls an LLM with a real capability snapshot (`capability_registry.snapshot()`) and the objective, then runs deterministic `_validate()`: unknown-agent, capability-mismatch, cyclic-dependency, out-of-plan-dependency, and safety-chain-ordering checks, each raising `PlanValidationError` and triggering a bounded retry (`_MAX_PLAN_ATTEMPTS = 3`) or an honest `cannot_plan` outcome. `TaskDependency` rows are persisted with real `prerequisite_task_id`/`dependent_task_id`/`policy`/`state` fields that `dependency_resolver.py` actually reads — this is a genuine graph consumed downstream, not informational text.

**Gap**: `capability_registry.find_by_capability` is called in exactly one runtime place — `task_engine.py:315`'s post-hoc reassignment fallback — **never by the planner itself**. The always-injected context scaffold (`ensure_research_scaffold`) hard-codes specific agent names (`"news_agent"`, `"sentiment_agent"`, `"market_analyst"`, `"portfolio_manager_agent"`) directly into `_CONTEXT_SCAFFOLD` rather than resolving them by capability. A second agent later declaring the same capability would never be selected for these scaffold tasks.

**Tests**: `tests/unit/test_plan_validation.py` (7 tests against `_validate` directly — cyclic dep, unknown agent, capability mismatch, out-of-plan dep, safety-chain reorder, empty plan); `tests/integration/test_org_planner.py::test_valid_objective_produces_a_persisted_validated_plan` and `test_two_different_objectives_produce_distinct_plans` (mocked LLM, real persisted `Task`/`TaskDependency` rows, confirmed distinct plans per distinct objective).

### 3.2 Agent task model & dependency waiting — **FULLY WIRED**

`dependency_resolver.py::ready_tasks` (line 48): for each candidate, `hard = _hard_deps_for(...)`; `if all(d.state == SATISFIED for d in hard):` the task is returned as ready; otherwise it is set to `WAITING_FOR_DEPENDENCY` and a `task.waiting_for_dependency` event names the unsatisfied prerequisite — this is the exact exclusion conditional. `evaluate_on_completion` (line 96) flips every dependent `TaskDependency` to `SATISFIED` when a prerequisite finishes and, if all of a dependent's hard deps are now satisfied, flips the dependent itself to `READY` — called directly from `task_engine.py::_run_dispatch_and_complete` in the same transaction as the prerequisite's completion, not a separate poll.

**Tests**: `tests/integration/test_org_concurrency.py::test_independent_tasks_overlap_and_dependents_wait` proves a dependent's `started_at` is `>=` the max completion time of all its prerequisites, using real recorded timings, not simulated ones. `tests/integration/test_org_blocked_dependency.py::test_upstream_failure_blocks_the_dependent_task` proves the negative case: a permanently-failed prerequisite leaves the dependent `BLOCKED`, never falsely `COMPLETED`.

### 3.3 Parallel agent execution — **FULLY WIRED**

`task_engine.py::run_scheduler_loop` (lines 107–114) submits every ready, concurrency-safe task to a real `ThreadPoolExecutor(max_workers=pool_size)` in one scheduling pass — genuine concurrent submission, not a disguised sequential loop. Claim-race protection uses `pg_advisory_xact_lock(hashtext(:k))` plus a conditional `UPDATE tasks SET status='running' ... WHERE status='ready' RETURNING id`; a `None` result from the claim means another worker already took it.

**Tests**: `tests/integration/test_org_concurrency.py` asserts ≥3 of 4 independent tasks genuinely overlap in wall-clock time (via a literal interval-overlap check, `ran_concurrently`). `tests/unit/test_task_claim_race.py::test_two_workers_race_one_ready_task_exactly_one_runs_it` spins up **two real Python threads** racing the identical ready task and asserts exactly one `ResultArtefact` row results — a genuine two-attacker race test, not a mock.

### 3.4 Agent-to-agent handoff/collaboration — **MISSING as a first-class concept**

A repository-wide search for "handoff"/"Handoff" across `src/` and `frontend/src` returns zero relevant matches — no `Handoff` model, table, or endpoint exists. The underlying provenance that *could* back a real handoff concept is genuinely wired: `artefact_store.py::mark_consumed` appends to `ResultArtefact.consumed_by_task_ids` and is called from `agent_invoker.py:619` every time a task dispatches against upstream artefacts, and `Task.received_inputs` is populated with the real artefact ids/types at the same moment (confirmed by `test_org_concurrency.py`'s assertion that the terminal `synthesize` task's `received_inputs` has exactly 5 entries). But there is no queryable sender→receiver→artefact→timestamp record and no API/UI named "handoff" — any UI arrow depicting one today would have to be inferred from task order, not read from a real object.

### 3.5 Agent collaboration / conflict review — **FULLY WIRED**

`decisions.py::detect_conflict` is a pure deterministic comparator (no LLM call) pairing `MarketContext.market_regime` against aggregated `SentimentReport` sentiment past a fixed threshold, and checking `RiskReport`/`ComplianceReport` rejections against any "proceed"-type artefact. It runs automatically inside `task_engine.py::_finalize`'s `_resolve_conflicts` call, before a run may reach a terminal state — not a manually-invoked utility that could be forgotten.

**Tests**: `tests/integration/test_org_conflict.py::test_opposing_market_and_sentiment_force_a_recorded_resolution` persists a genuinely bullish `MarketContext` alongside a genuinely negative `SentimentReport`, calls the real detection/resolution path, and asserts a recorded `OrganizationalDecision` with the correct kind and non-empty reason/next-step, plus both a `ceo.conflict_detected` and `ceo.decision.created` event. `test_high_severity_conflict_also_escalates_to_a_human_role` confirms high-severity conflicts additionally escalate.

### 3.6 Failure / retry / recovery — **PARTIALLY WIRED**

`task_engine.py::_handle_task_failure` genuinely re-queues a failed task (`retry_count += 1`, `status = READY`) while under `max_retries` (default 3), and only marks it permanently `FAILED` — propagating `BLOCKED` to dependents via `dependency_resolver.mark_unsatisfiable` — once the retry budget is exhausted. Retry attempts are preserved as distinct events in the append-only event log even though the `Task` row's own `failure_reason` column reflects only the final failure.

**Gap**: `tests/integration/test_org_failure_handling.py` and `test_org_blocked_dependency.py` both force **every** attempt to fail, covering only the total-exhaustion → escalation path. **No test exercises "fails once, recovers on retry"** — the code branch that re-queues a task is real and reachable, but is only ever exercised as an intermediate step on the way to permanent failure, never asserted as a distinct successful-recovery scenario.

### 3.7 Agent activity / events — **PARTIALLY WIRED**

`events.py::emit()` is a genuine single choke point: one function call does the Postgres insert, the optional audit-log write, and the Redis publish. 24+ real call sites across the orchestration layer use it, and every `Task.status`/`OrganizationRun.status` mutation found is paired with an `emit()` call in the same code block.

**Gaps found**:
- `TaskStatus.AWAITING_APPROVAL` is declared in `enums.py` but referenced nowhere else in the codebase — a purely aspirational value.
- `TaskStatus.RETRYING`, `WAITING_FOR_AGENT`, `SUPERSEDED`, `ESCALATED` are declared and appear in `.status.in_(...)` filter expressions but are **never actually assigned** to a real `Task.status` — e.g. `_handle_task_failure` emits an event named `"task.retrying"` while setting the actual column to `READY`, so the event name and the stored status diverge.
- **Approval creation is a silent transition**: `_open_paper_approval_request` writes the `ApprovalRequest` row and an audit entry but **never calls `events.emit()`** — only `approval.approved`/`approval.rejected` reach the event bus. The Approval Queue therefore learns about *new* pending approvals only via its own polling interval, not push.

### 3.8 Realtime updates — **FULLY WIRED**

The same `events.emit()` function performs both the Postgres write and the Redis publish (`ORGANIZATION_EVENT_CHANNEL`), so there is no separate "forgot to publish" call site to omit. `src/api/routers/streams.py`'s `/organization` WebSocket route subscribes to the identical channel name. The frontend hook `useOrganizationStream.ts` genuinely invalidates seven distinct React Query cache keys per incoming event (not merely appending to an unrendered array) and backfills gaps on reconnect via `GET .../events?after_sequence=`, deduplicating by `sequence` on both the backfill and live paths.

### 3.9 Approval workflow — **PARTIALLY WIRED — has a live bypass**

The intended path is real and RBAC-checked: `_persist_strategy_progress` sets `Strategy.status = "PendingPaperApproval"` and opens an `ApprovalRequest`; only `approvals.py::approve()`/`reject()` can move it out of that state, `reject()` requires a non-empty reason, and `tests/integration/test_org_approval_gate.py` covers RBAC denial, reject-without-reason (422), reject-with-reason outcome, and double-decision conflict (409).

**The bypass**: `POST /api/v1/strategies/{strategy_id}/promote` (`src/api/routers/strategies.py:1069`) accepts `to_status: Literal["Backtesting","PaperTrading","Live","Deprecated"]` for any strategy with a code version that is not `"Ideation"`, gated by the *same two roles* (`SystemAdministrator`, `PortfolioManager`) that decide `ApprovalRequest`s — but this handler **never checks for an existing pending/approved/rejected `ApprovalRequest`** and never requires `strategy.status == "PendingPaperApproval"`. Concretely: a strategy just **rejected** (now `"Deprecated"`, still has `current_version_id`) can be moved straight to `"PaperTrading"` through this endpoint, with no `ApprovalRequest` ever created or consulted. No existing test exercises this specific path — the one test that reaches `/promote` near Paper Trading territory targets `"Live"`, not `"PaperTrading"`, and the approval-gate test suite only confirms the endpoint *exists*, not that it respects approval state.

### 3.10 Audit trail — **FULLY WIRED for hash-chain mechanics; PARTIALLY WIRED for reference linkage**

The append-only trigger (`BEFORE UPDATE OR DELETE ON audit_log ... RAISE EXCEPTION`, plus a `REVOKE UPDATE, DELETE` grant removal) is real, migration-verified, and candidly documents its own residual gap (a table-owner role could still disable the trigger — an accepted, documented risk, not an overclaim). The SHA-256 hash chain is genuinely computed at write time and independently re-verified by `verify_chain()`, which is actually invoked from a real scheduled monitor (`audit_chain_monitor.py`), not merely defined and unused. `ApprovalRequest.audit_reference` is populated correctly.

**Gap**: `OrganizationalDecision.audit_reference`, `ResultArtefact.audit_reference`, and `Task.audit_reference` are all live FK columns that are **never written anywhere in the codebase** — `events.emit()` creates the underlying `AuditLog` row internally but never returns its id to the caller, so there is structurally no way for these three models to populate their own audit-reference column today, despite every one of their meaningful transitions producing a real, audited event.

### 3.11 Agent Console / Organization overview — **PARTIALLY WIRED**

`console/page.tsx` and `OrganizationOverview.tsx` are genuinely live — real `useQuery` polling, no hardcoded status counts (`byStatus` is computed by reducing over live run data). **No Task Board exists anywhere**: the closest equivalent is a single flat, unfiltered `<ul>` of all tasks in `runs/[runId]/page.tsx`, sorted by array order rather than grouped by status. The dependency graph (`OrgTaskGraph.tsx`) **is** genuinely data-driven — real topological depth computed via BFS from actual `TaskDependency` rows drives grid position, and real `dependency.state` drives edge color/dash-pattern — but it is a fixed-layout, non-interactive SVG (no pan/zoom/drag), and lives only on the run-detail page, not the top-level console.

### 3.12 Agent detail workspace & agent switching — **PARTIALLY WIRED, loses context**

`AgentDetail.tsx` genuinely binds `activity.recent_outputs` and `activity.recent_runs` to live data. But the link into it from a run's task list (`runs/[runId]/page.tsx`) passes **no run or task id** — `` `/console/agents/${t.assigned_agent}` `` — so the agent page is always a generic, run-agnostic view with no "back to this task" affordance, only a generic link back to `/console`. Of the 12 required sections:

| Section | Status |
|---|---|
| Current task / status | Real-ish (a generic "recent tasks" list, not a singled-out "current" task) |
| Dependencies | **Missing** |
| Waiting reason | **Missing** (the explainer logic exists in the same file but is never invoked here) |
| Inputs | **Missing** |
| Outputs | Real |
| Tools | **Missing** |
| Skills | **Missing** |
| Provider / model | A static "AUTO (routing.yaml)" / "no model — deterministic" label — not the actually-resolved identifier |
| Execution history | Real |
| Errors / retries | **Missing** |
| Handoffs | **Missing** (no such concept exists at all, per §3.4) |
| Downstream consumers | **Missing** |
| Audit | **Missing** |

### 3.13 Activity stream — **FULLY WIRED (merge/dedup); PARTIALLY WIRED (explanation)**

The merge of historical + live events is genuinely sequence-deduplicated on both the page (`mergeEvents`) and the streaming hook (`ingest()`'s `if (e.sequence <= seen) return`) sides, with real gap-filling backfill on reconnect. But `ActivityStream.tsx` renders only raw `event_type` + `subject_type/id` — there is no per-event plain-language "why," despite that explanatory text existing elsewhere in the app (`taskStateExplainer` on task cards, `reason`/`next_step` on decisions) and the product's explicit requirement that every major status answer "why."

### 3.14 Run history — **PARTIALLY WIRED**

No dedicated run-history route exists (no `console/runs/page.tsx` index). `OrganizationOverview.tsx`'s "Recent runs" card calls `api.orgRuns()` with no status filter, receiving the backend's default 50-row fetch, then client-truncates to 20 (`runs.slice(0, 20)`). The backend genuinely supports a `status` filter and up to `limit=200`, but nothing in the frontend exposes it, and there is no `offset`/cursor pagination server-side either.

### 3.15 Agent analytics — **PARTIALLY WIRED**

Success rate, and avg/p50/p95 duration are genuinely computed from the real `AgentRun` ledger (`src/agents/analytics.py`, using `numpy` percentile math over real query results, explicitly documented to return "only real days with at least 1 real run... never a zero-filled synthetic day"). **Retry counts, escalation counts, and token/cost usage are absent from this surface entirely** — not placeholders, simply not built.

### 3.16 Agent prompt management — **FULLY WIRED, one governance gap**

Every round trip is real: creating a version persists a real DB row (`is_active=False` by default); `PromptDiff.tsx` renders a genuine computed diff via the `diff` package's `diffLines()`; activation flips `is_active` in the database, and **every real agent node calls `get_active_prompt()` fresh on every invocation** (no caching), so a new activation takes effect on the very next run with no redeploy; rollback reuses the identical audited activation path (no silent overwrite — a new audited activation row records the reversion); the "Test" panel makes a genuine LLM call against the draft prompt, not a local-only JSON validation; and SA-only gating is enforced server-side via Casbin policy rows, not merely hidden in the UI.

**Gap**: `PromptVersionHistory.tsx`'s "Activate" button fires its mutation directly on click — no confirmation modal, and no requirement that the diff view have been opened first. An operator can activate a version they never diffed.

### 3.17 Per-agent provider/model configuration — **PARTIALLY WIRED — override has no effect on real runs**

The precedence chain (global routing → agent default → agent CUSTOM override → fallback) is real code (`src/orchestration/agent_config.py::resolve()`), re-validated live rather than trusted from save time. `llm_router.py::complete()` genuinely prepends a resolved `agent_name` override to the model chain **when one is supplied**. The UI only offers providers/models with real, configured credentials (`GET /providers`'s `is_configured` check), enforced again server-side on save (422 otherwise). AUTO-mode byte-identical behavior is genuinely regression-tested (`test_llm_router_auto_unchanged.py`).

**The break**: a grep of every real `complete(` call site — every file in `src/agents/nodes/`, plus `planner.py`, `agent_invoker.py`, `adhoc.py`, `chat.py` — shows **none of them pass `agent_name=`**. Only the Agent Settings "Test" endpoint and one unit test ever supply it. Setting `risk_manager_agent` to a specific, valid, configured custom model via the console is accepted, validated, and audited by the system — and **has zero effect** on which model `risk_manager.py` actually calls, because the node never identifies itself to the router.

### 3.18 Agent tools/skills configuration — **PARTIALLY WIRED backend catalog; MISSING UI; not enforced per-agent**

Global per-skill enable/disable is real and enforced at call time (`SkillRegistry.execute()` raises `SkillDisabledError` when a skill is globally off, synced against a real DB-backed state). A per-agent grant table, `AgentSkillMap` (`agent_name`, `skill_id`, `granted_by_user_id`, `granted_at`), exists with a complete, real CRUD API (`GET/POST/DELETE /skills/agent-map`), gated SA-only.

**Gaps**: no frontend anywhere references this table or API (`grep` for `agent-map`/`AgentSkillMap` across `frontend/src` returns zero matches) — there is no UI to view, grant, or revoke a per-agent skill assignment. And **no runtime code ever reads `AgentSkillMap`** — `SkillRegistry.execute()` takes no caller/agent-identity parameter at all, so granting a skill to one agent and withholding it from another currently changes nothing: any agent that calls `execute(name)` can use any globally-enabled skill, grant or no grant.

---

## 4. Audit Gap Analysis — re-verifying `docs/audit-2026-09.md`'s "RESOLVED" claims

The prior audit (`docs/audit-2026-09.md`) marks BUG-A through BUG-I and console findings C-1 through C-5 as resolved by `001-ceo-led-trading-org`. Independent re-verification against current code and tests confirms most of this, with **three corrections**:

| Claim | Independent re-verification | Verdict |
|---|---|---|
| **BUG-B**: "a real approval gate now exists" | True for the deployment-recommendation path specifically (§3.9's intended path). **False as a universal claim**: `/strategies/{id}/promote` bypasses the entire mechanism (§3.9's gap). This is exactly the "false completion" pattern BUG-B itself was written to catch, recreated one endpoint over. | **OVERSTATED — reopened as spec-kit US1** |
| **BUG-C**: "News/Sentiment/Portfolio outputs now consumed" | Traced the full consumer-side loop: `agent_invoker.py`'s handlers read the real Qdrant `news_sentiment` collection and real `portfolio_positions` table; `_context_assembly_handler` folds four artefact types into a `ResearchContext` that explicitly tracks `missing_inputs`/`coverage`; `strategy_generator.py:69-70` genuinely reads `state.research_context`. This is a closed loop, not a store-only side effect. | **CONFIRMED ACCURATE** |
| **BUG-G / C-1**: "stale caption fixed, now derived from live topology" | The old `agents/page.tsx` no longer exists; a repo-wide grep for the old literal strings returns zero hits; `console/page.tsx` genuinely renders `` `${topologyQuery.data.nodes.length} nodes, ${edges.length} edges` `` sourced from a real `graph-topology` query. | **CONFIRMED ACCURATE** |
| **C-4**: "prompt hot-swap has no diff-and-confirm" | A real diff component (`PromptDiff.tsx`, using `diffLines()`) was added and is genuinely wired into `PromptVersionHistory.tsx` — the "diff" half is fixed. The "confirm" half is **not**: `onClick={() => activate.mutate(v.version)}` fires immediately with no modal and no requirement the diff be viewed. | **PARTIALLY fixed — reopened as spec-kit US9** |
| **C-5**: "lifecycle labels vs. reality" | Recurred in a new form: `AWAITING_APPROVAL`/`RETRYING`/`WAITING_FOR_AGENT`/`SUPERSEDED`/`ESCALATED` are declared in the current `TaskStatus` enum and referenced in filter expressions, but never actually assigned by any code path (§3.7). | **Recurred — reopened as part of spec-kit US7** |

No other BUG-*/C-* item was found to be inaccurately marked resolved.

**Closure update (2026-09-12, `002-agent-organization-hardening` implementation)**:

- **BUG-B — RE-RESOLVED (US1, T001–T005)**. `has_approved_paper_request()` gates `promote_strategy`'s `to_status="PaperTrading"` transition; `/strategies/{id}/promote` now returns 409 without an `approved` `ApprovalRequest`. Verified with a genuine negative control (`tests/integration/test_org_approval_bypass_closed.py`): the guard was manually reverted, the exploit confirmed to still work, then restored and confirmed blocked — not just a test written to match the fix.
- **C-4 — RESOLVED (US9, T043–T045)**. `PromptVersionHistory.tsx` now tracks which versions have actually had their diff opened (`diffedVersions`, set in the diff-button click handlers) and requires a second explicit "Confirm" click after that before `Activate`/`Roll back` fire — both previously fired on a single click with no diff requirement. Cypress-tested against the real seeded `strategy_generator_agent` v1/v2 fixture, and manually verified end-to-end in a real browser (grant → confirm → activate → restore round-trip).
- **C-5 — RESOLVED (US7, T028–T035)**. `AWAITING_APPROVAL`/`WAITING_FOR_AGENT`/`SUPERSEDED` removed from `TaskStatus` (no code path ever produced them); `RETRYING` now set for real between a failure and the next dispatch claim; `ESCALATED` now set at the genuine "no available agent for this capability" branch (previously folded into generic `BLOCKED`, indistinguishable from a task blocked only because a dependency never satisfied). Every remaining `TaskStatus` value is reachable and test-covered; the pre-existing `test_org_agent_control.py` suite (from `001`) was updated to match this deliberate, more precise relabeling.

---

## 5. Feature Comparison

| Reference ZIP pattern | Current TradingOS | Required target | Gap | Backend needed | Frontend needed |
|---|---|---|---|---|---|
| Static per-agent detail panel | `AgentDetail.tsx`, context-free, 3/12 sections real | Context-aware, all 12 sections real | Large | Enrich existing `GET /agents/{id}/activity` by composing already-existing services | Thread run/task id through every agent link; rewrite `AgentDetail.tsx` |
| None (reference has no handoff concept either) | No `Handoff` entity | First-class, inspectable handoff record | Medium | New derived query (`handoffs.py`) off existing artefact-consumption data — no new table in the default path | New handoff inspector panel |
| Fake static progress bars/steps | Real per-task lifecycle, no kanban view | Task Board grouped by real status | Medium | None — existing `GET .../tasks` suffices | New Task Board component |
| Tone-tagged static event log | Real live event stream, no per-event "why" | Self-explaining activity stream | Small | Add a `reason` field at emit time for events that already compute one | Render inline |
| N/A | Approval bypass via `/promote` | Single enforcement point | Critical | One guard clause + one missing event emission | Approval Queue reflects both paths |
| N/A | Per-agent model override recorded but inert | Override actually used by real calls | Critical | Thread `agent_name=` through every node's `complete()` call | Show resolved (not just configured) model |
| N/A | Skill grants recorded but unenforced, no UI | Enforced + visible | Medium | Thread caller identity into `SkillRegistry.execute()` | New grant/revoke panel |

---

## 6. Product / Engineering User Story

**What are we building?** Not a new Agent Console — the real one already exists. We are closing eleven specific, evidenced gaps between what `001-ceo-led-trading-org` shipped and what it needs to be a trustworthy, fully-observable, non-bypassable organization: the CEO genuinely leads (already true, with one delegation path still hard-coded); specialists genuinely collaborate through typed artefacts (already true, but the collaboration is not yet *inspectable* as a first-class handoff); the console genuinely reflects reality in real time (already true for the parts it covers, but two required views — Task Board, complete Agent Workspace — don't exist yet, and the activity feed doesn't explain itself); and governance is genuinely non-negotiable (already true for the dedicated approval path, but not yet true for the whole system, because a second, older endpoint can walk around it).

**Why?** Because "recorded but inert" and "gated on one path but not another" are worse than "missing" — they create false confidence. An operator who sets a custom model for the risk manager, or who rejects a strategy's approval, has every reason to believe that decision took effect. Today, in both cases, it might not have.

**Who uses it?** The same owner/portfolio-principal persona the organization layer was built for, plus the `SystemAdministrator`/`PortfolioManager`/`RiskManager` roles who operate approvals, prompts, and provider/model configuration under RBAC.

**What does the CEO do, and how do agents collaborate?** Unchanged from `001-ceo-led-trading-org`'s real, verified behavior (§3.1–3.3, §3.5) — this feature only fixes the one remaining hard-coded delegation path (context scaffold) and gives the CEO's already-real artefact hand-offs a first-class, inspectable identity.

**What does the reference project teach us?** Purely visual vocabulary — an accent-color identity system, a tone-tagged event log, a two-panel deep-dive layout, and a step-timeline — nothing architectural, since it has no backend, no data model, and no real-time behavior of its own.

**What must be built, precisely?** See §7 and the full spec kit at [`specs/002-agent-organization-hardening/`](../specs/002-agent-organization-hardening/): one guard clause and one event emission (approval bypass); a mechanical "pass `agent_name=`" change across every real LLM call site (dead override); one new derived-query module and API endpoint (handoffs); one enriched existing endpoint and one rewritten component with context-threading (agent workspace); two new frontend components consuming already-existing data (Task Board, run history); one small server-side/shared-logic addition (self-explaining activity stream); one planner change and one enum cleanup (capability-based scaffold, lifecycle correctness); one parameter addition to the skill registry plus a new settings panel (skill enforcement); one frontend gating change (prompt confirm-before-activate); and one return-value change threaded to three call sites (audit-reference completeness). No new datastore, framework, or service.

**What tests prove it works?** Each of the eleven stories in the spec kit carries its own independent test, several specifically written to fail against the current (pre-fix) code — most importantly a test that asserts `/promote` now refuses a rejected strategy, and a static-analysis test asserting every real LLM call site passes `agent_name`, so neither gap can silently reappear.

---

## 7. Implementation Plan

Full detail — technical approach per story, constitution/safety check, file-level project structure, and 57 dependency-ordered tasks — is in the spec kit:

- [specs/002-agent-organization-hardening/spec.md](../specs/002-agent-organization-hardening/spec.md) — 11 user stories (US1–US11), each with priority, rationale, independent test, and acceptance scenarios, plus this report's evidence tables in spec form.
- [specs/002-agent-organization-hardening/plan.md](../specs/002-agent-organization-hardening/plan.md) — technical approach, constitution check (no safety-control changes, no new datastore/dependency), file-level project structure.
- [specs/002-agent-organization-hardening/data-model.md](../specs/002-agent-organization-hardening/data-model.md) — the only two schema-adjacent decisions (handoffs are derived, not stored, by default; `audit_reference` is a write-path fix, not a migration).
- [specs/002-agent-organization-hardening/tasks.md](../specs/002-agent-organization-hardening/tasks.md) — 57 tasks across 11 story-phases + final validation.

**Recommended delivery order**:

1. **Phase 1 — Governance-critical (US1, US2)**: close the live approval bypass and the inert provider/model override. Smallest, highest risk-reduction.
2. **Phase 2 — Observability core (US3–US6)**: handoffs, complete context-aware agent workspace, Task Board, self-explaining activity stream — the actual "agent console completion" this audit centers on.
3. **Phase 3 — Correctness cleanup (US7)**: capability-based scaffold delegation, task-lifecycle enum correctness.
4. **Phase 4 — Settings hardening (US8, US9)**: skill enforcement, prompt-activation confirmation.
5. **Phase 5 — Polish (US10, US11)**: run-history pagination, analytics/audit-reference completeness.

Nothing in this plan touches LangGraph, the task engine's core scheduling algorithm, the deterministic risk/compliance/kill-switch chain, or the datastore layer — every one of those was verified genuinely solid in §3 and is reused, not replaced.

No code has been written yet. This report and its accompanying spec kit are the complete analysis-and-specification deliverable requested before implementation begins.
