# Feature Specification: Agent Organization Hardening & Console Completion

**Feature Branch**: `002-agent-organization-hardening`

**Created**: 2026-09-12

**Status**: Draft

**Roadmap Epic**: `REL-097` (reserved — see Constitution Traceability below and `tasks.md` T058 for the recording task)

**Input**: User description: "Evolve the existing TradingOS Agent Console / Organization experience (shipped as `001-ceo-led-trading-org`, REL-095/096) using a supplied reference UI (`multi-agent-ai-console.zip`) as a visual/UX reference, while preserving and extending the existing backend and agent architecture. Do not take the shipped Organization Command Center at face value — verify every required behavior end-to-end before deciding what is complete, then close only the gaps that are real. Target behavior: CEO leads the organization (plans, delegates, runs independent work in parallel, waits on dependencies, coordinates review, handles failure, escalates, synthesizes, requests approval); agents behave like departments with real collaboration through tasks/artefacts/events; the console makes this visible in realtime; the user can switch from CEO to any specialist agent and inspect current task, status, dependencies, waiting reason, inputs, outputs, tools, skills, provider, model, execution history, errors, retries, handoffs, downstream consumers, and audit; a dedicated Agent Settings experience covers prompt/version/diff, provider/model (AUTO default preserved), tools/skills, and runtime configuration. Where a required capability is missing or only superficially wired, build the real backend rather than faking it in the frontend."

---

## Overview

`001-ceo-led-trading-org` (REL-095/096, 2026-09-10/11) replaced TradingOS's single fixed pipeline with a real CEO-led organization: a planner that delegates by capability, a task engine that runs independent work concurrently and blocks dependent work on real inputs, a typed artefact/event/decision model, a live Organization Command Center, and a dedicated Agent Settings area. This is not a green-field build.

A code-level re-verification (this spec's own diagnostic pass, not a re-read of prior documentation) found that **most of the core organizational mechanics are genuinely wired and test-covered** — parallel dispatch with advisory-lock claim races, dependency wait/wake, automatic conflict detection, and prompt version activation are all real. But several capabilities the product explicitly requires are **either not implemented, only partially wired, or actively bypassable**, and one is a governance-integrity defect (a second, ungated code path can move a strategy into Paper Trading without ever consulting the approval record that is supposed to be the sole gate). This spec closes exactly those gaps — it does not re-architect what already works.

**In scope**: `multi-agent-ai-console.zip` is the **primary UI/UX and interaction reference** for replacing/upgrading the existing TradingOS Agent Console / Organization experience — its layout, agent-card treatment, agent workspace structure, activity/log presentation, task visualization, and CEO-workspace framing are the design baseline this feature adopts and adapts for TradingOS (see the corrected `Reference ZIP Analysis` below). The reference's own backend is mocked, and that is **not** copied: every piece of the resulting UX is backed by real TradingOS data, extending backend/API/DB/event capability wherever the desired UX needs something that doesn't exist yet.

**Still out of scope**: replacing LangGraph, the task engine's core scheduling algorithm, the artefact/event data model, or any deterministic safety control (risk engine, compliance, kill switch) — all verified working and extended, not replaced; and replacing TradingOS's existing whole-app shell (top nav, account-scope switcher, command palette, notification center, the other 9 peer routes) with the reference's own single-page sidebar shell — the existing shell is independently verified as a more capable, already-integrated foundation (see `Reference ZIP Analysis`), so the reference's IA/visual language is adopted *within* `/console`'s own content, not as a replacement for the app shell around it.

---

## Constitution Traceability

Per constitution Principle I (Spec-Driven & Traceable), this feature must trace to (a) a requirement or decision in `Project Document and BluePrint/` and (b) a roadmap epic/exit criterion recorded in `TradingOS_ERDTM.xlsx`:

- **(a) Blueprint requirement/decision**: `Phase_7_Frontend_Architecture.md` §6 (the `/console` route-family specification) and `TradingOS_Master_Blueprint.md`'s Agent Console section both describe the Organization Command Center's required behavior — CEO-led delegation, real dependency-aware execution, a uniform agent detail view, live activity, and governed approval. This spec's Current-State Verification (below) is the audit of that description against shipped reality; the fourteen user stories (US1–US11 plus the 2026-09-12 Scope Correction's US12–US14) close the gaps found between the Blueprint's stated requirement and what is genuinely wired — and, for the presentation layer, genuinely *designed* to the reference-quality bar — end-to-end.
- **(b) Roadmap epic**: `REL-097`, reserved as the next available epic number after `REL-095`/`REL-096` (`Phase_14_Master_Development_Roadmap.md` §114–115). `tasks.md` T058 records this epic and its exit criteria (US1–US14's independent tests) in the roadmap and adds the corresponding `TradingOS_ERDTM.xlsx` traceability row before this feature is considered delivered — matching the same "ERDTM update is a delivery task" pattern `001-ceo-led-trading-org`'s own plan.md used for Principle I compliance.

---

## Scope Correction — 2026-09-12 (post-review)

The first draft of this spec treated the reference ZIP as informational only ("contributes four visual patterns, not an architecture to clone") and left the existing console's information architecture largely as-is, scoping frontend work to closing specific data-completeness gaps (US3, US4, US5, US6, US9). **This was corrected** after explicit review: the reference ZIP is the **primary UX/UI/interaction baseline** for redesigning the console's presentation layer — its agent-card treatment, agent workspace layout, activity-log presentation, task visualization, and CEO-centric framing must genuinely reshape the target UI, not merely inspire four cosmetic patterns layered onto an unchanged IA.

This correction does **not** change the backend-hardening scope (US1, US2, US3, US7, US8, US10, US11 remain exactly as specified — the CEO orchestration, task engine, dependency resolution, artefact/event model, and every deterministic safety control were independently verified real in the Current-State Verification below and are not being rebuilt). It **does** change and expand the frontend scope: US4, US5, and US6 are rewritten below to adopt the reference's IA rather than just filling data gaps in the existing layout, and three new stories are added — **US12** (Agent Fleet — a card-based live roster, department-grouped), **US13** (CEO Workspace — a rich, narration-driven deep-dive replacing the current admin-panel-style Organization Overview), and **US14** (Dependency graph interactivity — pan/zoom and real animated edge-activation). One explicit, evidence-based editorial boundary is drawn and held even under this expanded mandate: the reference's own *whole-app shell* (its sidebar, its four non-functional placeholder nav tabs) is not adopted, because TradingOS's existing top-nav shell (see below) is independently verified as a more capable, already-integrated, already-tested foundation — adopting the reference's IA happens *inside* that shell's content area, which is exactly what "adapt it to TradingOS, don't blindly clone unrelated content" (a requirement stated identically in both the original brief and this correction) requires.

---

## Reference ZIP Analysis (corrected — primary UX/UI/interaction baseline)

`multi-agent-ai-console.zip` is a single-page Next.js/Tailwind demo (~one 43-line `page.tsx`) with **no backend, no API, no state management, and no real-time anything** — every agent status, progress bar, "current thought," and activity-stream row is a hardcoded static array; nothing updates at runtime, and it has no Task/Run/Handoff/Approval data model at all. **This does not make its UX out of scope.** It means: the reference is a design/product/interaction reference, and TradingOS must build or extend the real backend needed to support the UX it inspires — never fake it in the frontend, and never adopt the reference's *mocked backend behavior* as if it were an architecture to copy.

Before mapping reference features to targets, the current TradingOS frontend's own visual/interaction foundations were independently re-verified (not assumed), because several of them turn out to already exceed what the reference demo offers:

- **App shell**: a real, deliberate, already-integrated shell exists — `AppShell` (`frontend/src/components/layout/app-shell.tsx`) wraps all 9 non-console routes plus `/console` in a sticky two-row `TopNav` (brand, connection status, account-scope Paper/Live/Both switcher, ⌘K command palette, notification center backed by the real audit log, profile menu, live clock; a responsive mobile-collapse nav row). This is materially more capable than the reference's single static sidebar with four non-functional placeholder tabs (Knowledge/Automations/Settings/Help all render an identical generic filler component) — hence the shell itself is not replaced (Scope Correction above).
- **Design tokens**: Tailwind v4 driven entirely by CSS custom properties (`frontend/src/app/globals.css`), a deliberate light/dark token pair (`data-mode="light"|"dark"`), a fixed brand gradient, and **fixed, explicitly-protected financial-semantic colors** (`--color-up`/`--color-down`/`--color-warn` — "a cosmetic theme preference must never touch a P&L color"). Any new agent-identity color system must be layered on top of these tokens, never repurpose them.
- **Component library**: shadcn/ui on base-ui primitives already exist and are reused, not reinvented — `Card` (already has a `fadeUp` entrance and an `interactive` hover-lift+glow variant), `Badge`, `IconBadge`, `Dialog`, `Sheet` (already used today for an agent detail drawer in `agent-registry.tsx`), `NumberTicker` (an animated-number primitive, currently unused by the console but exactly what the reference's KPI stat tiles need).
- **Motion**: `framer-motion` is a real, disciplined system already (`frontend/src/lib/motion.ts`'s named presets — `fadeUp`, `scaleIn`, `slideUp`, `staggerContainer`/`staggerItem`, `floatingIcon` — explicitly documented so "motion feels consistent rather than ad-hoc per component"). This is reused for every new component below, not supplemented with new animation infrastructure.
- **Existing reusable task-visualization pattern**: `frontend/src/components/strategies/kanban-board.tsx` + `strategy-card.tsx` already implement a real, tested, status-column board (for the Strategy `Ideation→Coding→Backtesting→PaperTrading→Live` lifecycle) with a `visibleStages` prop and per-column state styling. This is the direct adaptation target for the Task Board (US5), not a from-scratch build.
- **Existing state→color convention**: `graph-flowchart.tsx`'s `STATE_STYLES` and `OrgTaskGraph.tsx` already map task/node state (`pending`/`active`/`completed`/`failed`/`halted`, `satisfied`/`unsatisfied`) to color — this is extended with a *new, additive* per-agent identity color, not replaced.
- **No per-agent visual identity exists anywhere today** — agent/task identity in the current console is purely textual (`display_name`, a generic `Badge variant="secondary"` kind label); this is a genuine, real gap the reference's pattern closes.
- **No shared Skeleton/EmptyState component exists** — loading/empty states are ad hoc but consistent (`animate-pulse` placeholder divs, inline "No recent activity"-style text per component). New components follow this same idiom; retrofitting a shared component app-wide is explicitly out of scope for this feature.

### Reference vs. TradingOS Feature Matrix

| Reference UI/UX element | What it means / target TradingOS behavior | Existing TradingOS support | Backend/API/DB/Event gap | Frontend gap | Story |
|---|---|---|---|---|---|
| Sidebar + top bar app shell | N/A — TradingOS's own top-nav shell (10 peer routes, account-scope switcher, command palette, notification center) is kept; the reference's shell is not adopted | Already real and more capable (see above) | None | None | — (Scope Correction) |
| Overview KPI stat tiles (Active agents, Tasks completed, avg response, token efficiency) | A real KPI tile row (active agents, tasks completed today, avg task duration, success rate — real numbers, no fabricated "token efficiency" until real cost data exists) atop the CEO Workspace | `NumberTicker` primitive exists unused; `analytics.py` already computes real success-rate/duration | None beyond existing analytics endpoints (US11 adds retry/escalation counts) | New KPI tile row using `NumberTicker` + `Card` | US13 |
| Horizontal agent-card selector strip | A live, department-grouped Agent Fleet: card grid with per-agent accent color, real status, current task, health, resolved model/provider | `capability_registry.snapshot()` (real departments/capabilities), `Card`/`IconBadge`/`Badge`/`staggerContainer` primitives all real; current "Agents & Legacy Graph" tab is an admin enable/disable table, not a live fleet view | None new (existing agent-activity/registry endpoints suffice) | New `AgentFleet.tsx`, department-grouped, with a new agent-color CSS-custom-property system layered on existing tokens | US12 |
| Agent status dot / progress bar | Real status treatment (running/waiting/blocked/completed/failed/idle), never a fabricated progress percentage | `STATE_STYLES`-style state→color convention already exists | None | Extend existing convention with agent-identity color; no fake progress bars — real elapsed time/status only | US12 |
| Two-panel "agent deep-dive + live log" workspace | Rewrite `AgentDetail.tsx` into this exact two-panel IA: left = identity/current task/status/dependencies/waiting-reason/inputs-outputs/tools-skills/provider-model/errors-retries; right = this agent's own filtered activity + handoff timeline | US4's data-completeness work (T017) and US3's handoffs (T012) already planned | None beyond US2/US3/US4/US8/US11's existing plan | Restructure `AgentDetail.tsx` layout; add agent-color identity; optional `Sheet`-based quick-peek | US4 (rewritten) |
| "Current thought" callout | **Not adopted as-is** (would expose fabricated/private model reasoning) — replaced with real, event-sourced operational narration (see Activity timeline row) | — | — | — | US4, US13 |
| Vertical step-timeline (execution path) | A real per-task/run timeline (checkmark = completed, spinner = running, empty = pending) sourced from real task/event state, not a hardcoded `i < 3` | `taskStateExplainer`, real task/event timestamps already exist | None | New timeline component inside Agent Workspace / run detail | US4 (rewritten) |
| Tone-tagged static event log | Real live tone-tagged Activity Stream: `OrganizationalEvent.event_type` families (`plan.*`/`task.*`/`agent.*`/`dependency.*`/`result.*`/`review.*`/`approval.*`/`ceo.decision.*`) mapped to a small color legend, each row also carrying a plain-language reason | Real live merge/dedup already works (Verification #13); `reason` field being added (US6/T025) | None beyond US6's existing plan | Apply tone palette to `ActivityStream.tsx`; reuse the same feed (filtered) for CEO Workspace's narration | US6 (rewritten), US13 |
| Raw "execution trace" terminal block | Not adopted as a fake terminal-styled JSON dump; real errors/retries/audit references are shown as structured data in the Agent Workspace instead | — | — | — | US4 (rewritten) |
| Static agent grid (Agents tab) | Superseded by the Agent Fleet (see above); the existing admin enable/disable table is retained as a distinct "manage" affordance, not removed | Existing `AgentRegistry` component | None | Fleet view added alongside, not replacing, admin registry | US12 |
| Non-functional placeholder tabs (Knowledge/Automations/Settings/Help) | Not adopted — these are unstyled demo filler with no real design; TradingOS's own real Agent Settings pages (prompt/provider/skills) already exist and are extended (US8, US9) using the existing design system for visual consistency, no IA change needed | Real `/settings/agents/[agentId]` pages exist | None new | Visual-consistency pass only (Card/Badge/motion), no new page | US9 (visual note only) |
| No dependency/workflow graph in reference at all | TradingOS's own dependency graph (`OrgTaskGraph.tsx`) is already real (topological depth, real edge state) but visually minimal/non-interactive — upgraded independently of the reference (which has nothing equivalent) with pan/zoom and animated edge-activation on real `dependency.satisfied` events | Real depth/state computation already exists (Verification #11) | None | Interactivity upgrade to `OrgTaskGraph.tsx` | US14 |
| No agent department/hierarchy grouping in reference | TradingOS's real department taxonomy (Executive, Market Intelligence, Research, Quant, Risk & Governance, Portfolio, Operations — from `001`'s capability registry) is surfaced visually for the first time via department-grouped Fleet cards | Already real in `capability_registry.py` | None | Department-grouped layout in `AgentFleet.tsx` | US12 |
| Dialog/Sheet drawer patterns | Reused as-is for: approval decision confirmation, prompt-activation confirm (US9), optional agent quick-peek card | Real `Dialog`/`Sheet` (base-ui) already used today (`agent-registry.tsx`'s detail sheet) | None | Apply existing primitives to new confirm flows | US9 |
| CSS-only motion, static progress | Reused TradingOS's own more sophisticated `framer-motion` vocabulary (`fadeUp`/`scaleIn`/`slideUp`/`staggerContainer`/`floatingIcon`) for every new component | Already real and documented | None | Apply existing presets; no new animation system | Cross-cutting (US12–US14) |
| Loading/empty/error states (fake in reference — its "empty states" never actually occur) | New components (Fleet, Task Board, CEO Workspace, Dependency Graph) follow TradingOS's existing ad-hoc-but-consistent per-component idiom (`animate-pulse` placeholders, honest inline empty text) | Existing idiom, not a shared component, but consistent | None | Apply idiom per new component; no app-wide retrofit | Cross-cutting |
| Responsive collapse | TradingOS's existing `md` breakpoint mobile-nav collapse pattern is reused for new console-internal components where they need to collapse (e.g., Fleet grid → stacked cards) | Already real and documented (`TopNav`'s mobile behavior) | None | Apply existing breakpoint conventions to new grids | Cross-cutting |

No part of the reference project's **data** (its hardcoded fixtures), its **non-functional buttons**, its **`SimplePage` placeholder tabs**, or its **hardcoded dark-only theming that bypasses its own shadcn tokens** is adopted — these remain explicitly out of scope as demo artifacts, not design patterns.

---

## Current-State Verification (evidence-based, 2026-09-12)

Verdict scale: **FULLY WIRED** (real, end-to-end, test-covered) · **PARTIALLY WIRED** (real logic exists but has a material gap) · **STATIC/MOCK** (looks real, isn't) · **MISSING**.

| # | Capability | Verdict | Evidence |
|---|---|---|---|
| 1 | CEO orchestration & delegation | **PARTIALLY WIRED** | `planner.py::generate_plan` genuinely uses an LLM + deterministic `_validate` (cyclic/unknown-agent/capability-mismatch checks) to produce a persisted, per-objective-distinct plan (`test_org_planner.py`). But `capability_registry.find_by_capability` is called only in the runtime reassignment fallback (`task_engine.py:315`), never by the planner itself; the always-injected context scaffold (`ensure_research_scaffold`) hard-codes agent names (`"news_agent"`, `"sentiment_agent"`, …) instead of resolving by capability. |
| 2 | Agent task model & dependency waiting | **FULLY WIRED** | `dependency_resolver.py::ready_tasks` excludes a task with any unsatisfied hard dependency; `evaluate_on_completion` flips dependents `waiting_for_dependency → ready` in the same transaction as the prerequisite's completion. Proven by `test_org_concurrency.py` (dependents start only after every prerequisite's completion) and `test_org_blocked_dependency.py` (permanent upstream failure → dependent `BLOCKED`, never falsely `COMPLETED`). |
| 3 | Parallel agent execution | **FULLY WIRED** | `task_engine.py::run_scheduler_loop` submits all ready, concurrency-safe tasks to a real `ThreadPoolExecutor`; claim races are closed by `pg_advisory_xact_lock` + a conditional `UPDATE … WHERE status='ready'`. `test_task_claim_race.py` runs two real threads against one ready task and asserts exactly one `ResultArtefact` is produced. |
| 4 | Agent-to-agent handoff | **MISSING as a first-class concept** | No `Handoff` model, table, or endpoint exists anywhere (`grep -ri handoff src/ frontend/src` — zero relevant hits). The underlying provenance is real (`artefact_store.mark_consumed` populates `ResultArtefact.consumed_by_task_ids`, and `agent_invoker.dispatch` populates `Task.received_inputs` from real upstream artefacts — asserted in `test_org_concurrency.py`), but there is no queryable sender→receiver→artefact→timestamp record, and no API/UI surface named "handoff." Any UI arrow between agents today would have to be inferred from task order, not read from a real handoff. |
| 5 | Agent collaboration / conflict review | **FULLY WIRED** | `decisions.py::detect_conflict` runs automatically inside `task_engine._finalize` before a run reaches a terminal state (not a manually-invoked utility); `test_org_conflict.py` proves an opposing bullish-`MarketContext`/negative-`SentimentReport` pair produces a recorded `OrganizationalDecision` and, at high severity, an `escalate_human` decision. |
| 6 | Failure / retry / recovery | **PARTIALLY WIRED** | `_handle_task_failure` genuinely re-queues a task (`status = READY`, `retry_count += 1`) up to `max_retries` before permanent `FAILED` + downstream `BLOCKED` propagation; retry attempts are preserved in the append-only event log. `test_org_failure_handling.py` and `test_org_blocked_dependency.py` cover total-exhaustion → escalation. **No test exists for the recovery path** (fails once, succeeds on retry, run completes) — the code path is real and reachable but unverified in isolation. |
| 7 | Agent activity / events | **PARTIALLY WIRED** | `events.emit()` is a genuine single choke point (DB insert + Redis publish + optional audit entry in one function), and 24+ real call sites use it. But `TaskStatus.AWAITING_APPROVAL`, `RETRYING`, `WAITING_FOR_AGENT`, `SUPERSEDED`, `ESCALATED` are declared in the enum and referenced in query filters but **never actually assigned** to a `Task.status` anywhere in the codebase — a lifecycle/reality mismatch (the same defect class as the original audit's C-5). Separately, **`approval.requested` is never emitted** — only `approval.approved`/`approval.rejected` reach the event bus, so the console's Approval Queue relies on polling, not push, for new approvals. |
| 8 | Realtime updates | **FULLY WIRED** | The same `events.emit()` call does the Postgres write and the Redis publish, so there is no "forgot to publish" seam. `useOrganizationStream.ts` genuinely invalidates seven live React Query keys per incoming event (not just appending to an unrendered array), dedupes by `sequence`, and backfills gaps via `after_sequence` on reconnect. |
| 9 | Approval workflow | **PARTIALLY WIRED — has a live bypass** | The intended path (`_persist_strategy_progress` → `PendingPaperApproval` → `ApprovalRequest` → `approvals.py::approve/reject`) is real, RBAC-checked, and test-covered (`test_org_approval_gate.py`). **However**, `POST /api/v1/strategies/{id}/promote` (`src/api/routers/strategies.py:1069`) accepts `to_status="PaperTrading"` for any strategy with a code version that isn't in `"Ideation"`, gated by the *same two roles* (`SystemAdministrator`, `PortfolioManager`) that decide approvals — but it never checks for an existing `ApprovalRequest`, never requires `status == PendingPaperApproval`, and never creates/references an approval record. A strategy just **rejected** (now `Deprecated`) can be promoted straight to Paper Trading through this endpoint with zero approval trail. This recreates the exact "false completion" pattern the original approval-gate work was built to close, one endpoint over. |
| 10 | Audit trail | **FULLY WIRED for the hash-chain mechanics; PARTIALLY WIRED for reference linkage** | The append-only trigger, `REVOKE`, and hash-chain compute/verify (`src/core/audit.py::verify_chain`) are real and actively monitored (`audit_chain_monitor.py`). `ApprovalRequest.audit_reference` is populated. But `OrganizationalDecision.audit_reference`, `ResultArtefact.audit_reference`, and `Task.audit_reference` are all live FK columns that are **never written** anywhere in the codebase — `events.emit()` creates the underlying `AuditLog` row internally but never returns it, so callers have no id to store back. The audit event exists; the forward-reference from the domain row to it does not. |
| 11 | Agent Console / Organization overview | **PARTIALLY WIRED** | `console/page.tsx` and `OrganizationOverview.tsx` are genuinely live (real `useQuery` polling, no hardcoded status counts). **No Task Board exists** — the closest thing is a single flat, unfiltered `<ul>` of all tasks in `runs/[runId]/page.tsx`. The dependency graph (`OrgTaskGraph.tsx`) is genuinely data-driven (real topological depth → grid position, real dependency `state` → edge color/dash) but is a fixed-layout SVG, not interactive. |
| 12 | Agent detail workspace & agent switching | **PARTIALLY WIRED — loses context** | `AgentDetail.tsx` genuinely binds outputs, recent-tasks, and execution-history to live data. But navigating to it from a run's task list passes **no run/task id** (`Link href="/console/agents/${t.assigned_agent}"`), so the agent page is always a generic, run-agnostic view — the explicit product requirement ("selecting an agent inherits the active run/task/context") is not met. Of the 12 required sections (current task, status, dependencies, waiting reason, inputs, outputs, tools, skills, provider/model, execution history, errors/retries, handoffs, downstream consumers, audit), only current-task-ish (recent tasks), outputs, and execution history are genuinely rendered; dependencies, waiting reason, inputs, tools, skills, errors, retries, handoffs, downstream consumers, and audit are **absent from this component** (some of that logic, e.g. `taskStateExplainer`, exists in the same file but is never invoked inside `AgentDetail` itself). Provider/model shows only a static "AUTO (routing.yaml)" / "no model — deterministic" label, not the actually-resolved identifier. |
| 13 | Activity stream | **PARTIALLY WIRED** | Live/historical merge is real and correctly deduplicated by `sequence` (`mergeEvents`, plus `useOrganizationStream`'s own `ingest()` guard). But individual events render only `event_type` + `subject_type/id` — no human-readable "why" per event; self-explaining status text (`taskStateExplainer`) exists only on task cards, not on the event feed itself. |
| 14 | Run history | **PARTIALLY WIRED** | No dedicated run-history route exists (no `console/runs/page.tsx`). `OrganizationOverview.tsx`'s "Recent runs" fetches the backend default of 50 runs with no status filter and client-truncates to 20 — the backend supports a `status` filter and up to `limit=200`, but nothing in the frontend exposes it, and there is no pagination (`limit`-only, no `offset`, server-side). |
| 15 | Agent analytics | **PARTIALLY WIRED** | Success rate, avg/p50/p95 duration, and real daily volume are genuinely computed from the `AgentRun` ledger (`src/agents/analytics.py`, no hardcoded numbers, no zero-filled synthetic days). Retry counts, escalation counts, and token/cost usage are **not present at all** in the analytics surface. |
| 16 | Agent prompt management | **FULLY WIRED, one governance gap** | Create/activate/rollback/test are all real round-trips: activation flips `is_active` in the DB and every real agent node calls `get_active_prompt()` fresh (no caching) on every invocation, so a new version takes effect on the very next run; rollback reuses the same audited activation path; the diff view (`PromptDiff.tsx`) uses a real `diffLines()` computation; SA-only gating is enforced server-side via Casbin, not just hidden in the UI. **Gap**: `PromptVersionHistory.tsx`'s Activate button fires the mutation directly with no confirmation step and no requirement that the diff have been viewed first — an operator can activate a version they never diffed. |
| 17 | Per-agent provider/model configuration | **PARTIALLY WIRED — override has no effect on real runs** | The full precedence chain, DB row, API, audit, and UI (restricted to actually-configured providers/models) are real. `llm_router.py::complete()` genuinely prepends a resolved `agent_name` override to the fallback chain when one is supplied. **But no real LangGraph node or orchestration handler ever passes `agent_name=` to `complete()`** — every call site (`ceo.py`, `market_analyst.py`, `risk_manager.py`, `compliance.py`, `strategy_generator.py`, `sentiment_agent.py`, etc.) calls `complete(task_type, messages)` with no agent identity. Setting `risk_manager_agent` to a specific custom model via the console is accepted, validated, and audited — and has **zero effect** on which model `risk_manager.py` actually calls. AUTO-mode byte-identical behavior is genuinely tested (`test_llm_router_auto_unchanged.py`). |
| 18 | Agent tools/skills configuration | **PARTIALLY WIRED backend catalog; MISSING UI; not enforced per-agent** | Global per-skill enable/disable is real and enforced at call time (`SkillRegistry.execute` raises `SkillDisabledError`). A per-agent grant table (`AgentSkillMap`) and its CRUD API exist and are real, audited-adjacent database operations. But **no frontend UI references it anywhere** (`grep` for `agent-map`/`AgentSkillMap` in `frontend/src` returns zero hits), and **no runtime code ever reads `AgentSkillMap`** — `SkillRegistry.execute()` takes no caller identity at all, so granting a skill to one agent and not another currently changes nothing about who can actually invoke it. |

**Files verified** (representative, not exhaustive): `src/orchestration/{planner,task_engine,dependency_resolver,decisions,artefact_store,agent_invoker,events,approvals,agent_config,capability_registry}.py`; `src/agents/{llm_router,prompt_registry,control}.py`; `src/agents/tools/registry.py`; `src/models/{orchestration,approval,agent_config,skill,audit}.py`; `src/api/routers/{organization,agent_settings,strategies,streams,skills}.py`; `src/core/audit.py`; `frontend/src/components/console/*.tsx`; `frontend/src/components/agent-settings/*.tsx`; `frontend/src/hooks/useOrganizationStream.ts`; `tests/unit/test_{plan_validation,task_claim_race,llm_router_auto_unchanged}.py`; `tests/integration/test_org_{planner,concurrency,blocked_dependency,conflict,failure_handling,approval_gate}.py`.

---

## Audit Gap Analysis

`docs/audit-2026-09.md` marks BUG-A through BUG-I and C-1 through C-5 as "RESOLVED" by `001-ceo-led-trading-org`. Independent re-verification confirms most of that, with three corrections:

| Audit claim | Re-verification | Status here |
|---|---|---|
| BUG-B: "real approval gate now exists" | **OVERSTATED.** True for the deployment-recommendation path; **false as a universal claim** — `/strategies/{id}/promote` bypasses the entire `ApprovalRequest` mechanism (Verification #9). | **Reopened as US1** |
| BUG-C: "News/Sentiment/Portfolio outputs now consumed" | **CONFIRMED ACCURATE** — traced the full consumer-side loop into `strategy_generator.py`'s use of `state.research_context`. | Closed, no action |
| BUG-G / C-1: "stale caption fixed" | **CONFIRMED ACCURATE** — caption is now derived from live `graph-topology` query; old strings absent. | Closed, no action |
| C-4: "prompt hot-swap has no diff-and-confirm" | **PARTIALLY fixed.** A real diff view was added and is wired up; the "confirm" half is still absent (Verification #16). | **Reopened as US9** |
| C-5: "lifecycle labels vs. reality" | **Recurred in a new form.** `AWAITING_APPROVAL`/`RETRYING`/`WAITING_FOR_AGENT`/`SUPERSEDED`/`ESCALATED` are declared but unreachable (Verification #7). | **Reopened as part of US7** |

No other BUG-*/C-* items were found to be inaccurately marked resolved.

---

## Feature Comparison

| Reference ZIP pattern | Current TradingOS | Required target | Gap | Backend needed | Frontend needed |
|---|---|---|---|---|---|
| Static per-agent "detail" panel | `AgentDetail.tsx`, context-free, 3/12 sections real | Context-aware, all 12 sections real | US4 | Expose dependencies/inputs/tools/skills/errors/retries/downstream-consumers/audit on the existing agent-activity endpoint | Thread run/task id through the agent link; render all sections |
| None (no handoff concept in reference either) | No `Handoff` entity | First-class, inspectable handoff record | US3 | New `Handoff` derivation (or materialized view) off existing artefact-consumption data + API | Handoff inspector panel |
| Fake progress bars / static "steps" list | Real per-task lifecycle, but no kanban view | Task Board grouped by real status | US5 | none (existing `GET .../tasks` suffices) | New Task Board component |
| Tone-tagged static event log | Real live event stream, no per-event "why" | Self-explaining activity stream | US6 | Small: expose a `reason` string alongside `event_type` where derivable | Render the reason inline |
| N/A | Approval bypass via `/promote` | Single enforcement point | US1 | Guard `/promote` against approval state | Approval Queue reflects both paths |
| N/A | Per-agent model override recorded but inert | Override actually used by real calls | US2 | Thread `agent_name=` through every node's `complete()` call | Show resolved (not just configured) model in Agent Detail |
| N/A | Skill grants recorded but unenforced, no UI | Enforced + visible | US8 | Thread caller identity into `SkillRegistry.execute()` | Skill grant/revoke panel |

---

## Clarifications

### Session 2026-09-12

- Q: Is the reference ZIP's visual style mandatory, or a starting point? → A: Starting point only — adapt colors/typography/tone-tagging to TradingOS's existing dark/light shadcn token system (do not hardcode literal dark colors as the reference does); do not adopt its non-functional placeholder tabs.
- Q: Should `/strategies/{id}/promote` be removed, or gated? → A: Gated — it remains the generic Kanban-move endpoint for `Backtesting`↔`Live` and other non-approval transitions (unchanged behavior there); only the `* → PaperTrading` transition must consult `ApprovalRequest` state, matching the existing dedicated approval path's own rule.
- Q: Should `AWAITING_APPROVAL`/`RETRYING`/`WAITING_FOR_AGENT`/`SUPERSEDED`/`ESCALATED` be implemented for real, or removed from the enum? → A: Implement `RETRYING` and `ESCALATED` for real (they describe states the engine already transiently occupies but doesn't record); remove `AWAITING_APPROVAL`, `WAITING_FOR_AGENT`, and `SUPERSEDED` from the `TaskStatus` enum and any dead filter expressions referencing them, since no code path produces them and no product requirement needs a task-level (as opposed to run/strategy-level) approval-waiting state.
- Q: Does per-agent skill enforcement need to block on missing grants immediately, or can it start as observe-only (log a warning) before hard-enforcing? → A: Hard-enforce from the start, but seed every currently-enabled `(agent, skill)` pair actually exercised in the last 30 days of `AgentRun`/event history as a granted row during migration, so existing behavior does not silently break on cutover.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — The Paper Trading approval gate cannot be bypassed (Priority: P1)

Any transition of a strategy into Paper Trading — through any endpoint — is only possible via a decided, approved `ApprovalRequest`. The generic strategy-promotion endpoint is guarded by the same rule the dedicated approval flow enforces, and `approval.requested` joins `approval.approved`/`approval.rejected` on the live event bus so the Approval Queue never depends on polling to learn about new work.

**Why this priority**: This is a live governance-integrity defect, not a missing feature — the current system can be operated in a way that produces exactly the false-completion pattern (`strategy silently promoted with no real approval`) that `001-ceo-led-trading-org` was built to eliminate.

**Independent Test**: Reject an `ApprovalRequest` for a strategy (status becomes `Deprecated`); attempt `POST /strategies/{id}/promote {to_status: "PaperTrading"}` as `SystemAdministrator`; confirm it is rejected (409/422) rather than succeeding. Separately, create a fresh deployment recommendation and confirm an `approval.requested` event is observable on the `/organization` WebSocket the moment the `ApprovalRequest` is created, without any client poll.

**Acceptance Scenarios**:

1. **Given** a strategy with no `ApprovalRequest` in `pending`/`approved` state, **When** any authorized role calls `/promote` with `to_status="PaperTrading"`, **Then** the call fails with a clear error naming the missing approval, and no status change occurs.
2. **Given** a strategy whose most recent `ApprovalRequest` was `rejected`, **When** `/promote` is called with `to_status="PaperTrading"`, **Then** the call fails the same way — a rejection is not overridable through this path.
3. **Given** a strategy whose `ApprovalRequest` was `approved`, **When** `/promote` is called with `to_status="PaperTrading"` (e.g., re-applying after an unrelated status change), **Then** it succeeds, matching today's dedicated-path behavior.
4. **Given** a new deployment recommendation, **When** the `ApprovalRequest` is created, **Then** an `approval.requested` event is emitted, audited, and visible on the WebSocket stream and in the Approval Queue without a manual refresh.
5. **Given** any non-`PaperTrading` target status (`Backtesting`, `Live`, `Deprecated`), **When** `/promote` is called by an authorized role, **Then** behavior is unchanged from today (this story narrows one transition only).

---

### User Story 2 — Per-agent provider/model overrides actually take effect (Priority: P1)

When an authorized operator sets an agent's `provider_model_mode` to `CUSTOM` with a specific provider/model, the very next real invocation of that agent uses it. AUTO-mode agents remain byte-identical to today.

**Why this priority**: The feature is fully built end-to-end except for the one call that matters; today it is silently inert, which is worse than not existing — an operator can believe they've pinned `risk_manager_agent` to a specific model and be wrong.

**Independent Test**: Set `market_analyst_agent` to `CUSTOM` with a specific configured provider/model; trigger a real organization run that dispatches a market-analysis task; confirm (via the resulting `ResultArtefact.provenance.model_used`/`provider_used`, already a tracked field) that the custom pair was actually used, not the AUTO chain's head. Revert to AUTO and confirm the next run's provenance reflects the original routing.

**Acceptance Scenarios**:

1. **Given** an agent set to `CUSTOM`, **When** that agent's node/handler makes its LLM call, **Then** `complete()` is invoked with `agent_name=<that agent's slug>` and the resulting artefact's provenance shows the configured provider/model.
2. **Given** an agent left at `AUTO`, **When** it runs, **Then** behavior and the resolved provider/model are unchanged from pre-existing routing (regression-guarded by the existing `test_llm_router_auto_unchanged.py`).
3. **Given** every LangGraph node function and every orchestration capability handler that calls `complete()`, **When** audited, **Then** each passes its own agent's slug as `agent_name` — no call site is missed (enforced by a repo-wide test, not spot-checked).
4. **Given** the Agent Detail workspace (US4), **When** viewing an agent with a `CUSTOM` override, **Then** the displayed provider/model is the actually-resolved identifier from the most recent real call's provenance, not a static "AUTO/deterministic" label.

---

### User Story 3 — Agent-to-agent handoffs are first-class and inspectable (Priority: P2)

Every time one agent's output becomes another task's input, a discrete, queryable **Handoff** record exists: sender agent, receiver agent, task, artefact(s) delivered, timestamp, and — where the required inputs for the receiving task were only partially available — what was *not* delivered.

**Why this priority**: This is an explicit product requirement ("handoffs must be inspectable... not a meaningless arrow") with no first-class backing today; the underlying data (`consumed_by_task_ids`, `received_inputs`) already exists and only needs to be surfaced as its own entity/view.

**Independent Test**: Run an objective where `strategy_research` consumes `MarketContext` + `ResearchContext`; query the new handoffs endpoint for that run and confirm it returns one handoff row per (producing task → consuming task) pair with the correct artefact type and timestamp, matching `Task.received_inputs` and `ResultArtefact.consumed_by_task_ids` exactly.

**Acceptance Scenarios**:

1. **Given** a completed run, **When** its handoffs are listed, **Then** every artefact consumption recorded in `received_inputs`/`consumed_by_task_ids` appears as exactly one handoff row (no duplicates, none missing).
2. **Given** a task whose `required_inputs` were only partially satisfied at dispatch (reduced-coverage path, US4 of `001-ceo-led-trading-org`), **When** its handoff is inspected, **Then** the handoff explicitly lists what was expected but not delivered.
3. **Given** the Agent Detail workspace, **When** viewing an agent, **Then** its inbound handoffs (what it received, from whom) and outbound handoffs (what it produced, consumed by whom) are both visible.
4. **Given** no new database table is strictly required (handoffs are derivable from existing rows), **When** implemented, **Then** the derivation is either a queryable view/query or a lightweight materialized table populated at the same transaction as `mark_consumed` — not a frontend-side inference from task order.

---

### User Story 4 — Agent workspace is complete, context-aware, and reference-quality (Priority: P2)

Selecting an agent — from a run's task list, from the Agent Fleet (US12), or directly by URL — opens a **two-panel workspace** (the reference ZIP's "agent deep-dive + live log" IA, adapted to TradingOS's own component library): the left panel is this agent's identity (name, department, agent-identity accent color, avatar/icon) plus current task, task status, dependencies, waiting reason, inputs, outputs, tools, skills, resolved provider/model, execution history, and errors/retries; the right panel is this agent's own filtered activity + handoff (US3) timeline, rendered as a real vertical step-timeline (checkmark = completed, spinner = running, empty circle = pending — sourced from real task/event state, never a hardcoded index) plus downstream consumers and audit references. A horizontal Agent Fleet strip (US12's cards, reused) sits above the two panels for in-context switching to another agent without leaving the run. Arriving from a specific run/task preserves that context (the workspace opens scoped to it, with a way back).

**Why this priority**: This is the single most-referenced product requirement across the brief and is currently the biggest concrete gap — not just in data completeness (9 of 12 required sections absent; context is lost on every navigation into it) but in information architecture (today's workspace is a single generic column, not the reference-quality deep-dive the product vision calls for).

**Dependency note**: two of this story's 12 sections are sourced from other stories delivered later in the recommended phasing — tools/skills grants from US8 (`plan.md` Phase 4) and populated audit references from US11 (`plan.md` Phase 5). This story does not wait for either: it ships with those two sections in an explicit, honestly-labeled "not yet enforced" / "not yet linked" state (AC5) until US8/US11 land, at which point they upgrade to real data with no further change to this story's own code. This is a deliberate incremental-delivery choice, not an oversight — see `plan.md`'s Phasing section for the cross-story sequencing rationale.

**Independent Test**: From an active run's task list, click into an agent; confirm the URL/route carries the run and task id and the workspace opens already scoped to that task (not a generic view); confirm all 12 required sections render real data (or an honest empty/not-applicable/not-yet-enforced state per AC5) for at least one graph-node agent and one non-graph (scheduled/registry-only) agent.

**Acceptance Scenarios**:

1. **Given** a task assigned to `risk_manager_agent` inside a specific run, **When** the operator clicks through to that agent, **Then** the route includes the run id (and task id where applicable) and the page shows a "back to run" affordance.
2. **Given** any agent, **When** its workspace is viewed, **Then** dependencies and waiting-reason (reusing `taskStateExplainer`), inputs, tools/skills (from the real `AgentSkillMap`/capability registry, once US8 lands), resolved provider/model (US2), errors/retries, handoffs (US3), downstream consumers, and audit references (once US11 lands) are all present.
3. **Given** an agent with no current task, **When** its workspace is viewed, **Then** it honestly shows "idle" / "no active task" rather than stale data from a prior run.
4. **Given** a non-graph (scheduled or registry-only) agent, **When** its workspace is viewed, **Then** the same section set renders with agent-appropriate content (e.g., a scheduled agent shows its cron cadence instead of a live dependency graph position).
5. **Given** this story ships before US8 and/or US11, **When** the tools/skills or audit-reference sections are viewed, **Then** each renders an explicit, honest "not yet enforced" / "not yet linked" label rather than a blank space or fabricated data — never presented as if it were complete.
6. **Given** the workspace is open, **When** the operator uses the Agent Fleet strip above the two panels, **Then** clicking a different agent's card switches the workspace to that agent without a full page navigation, preserving the active run context.
7. **Given** the right-panel execution timeline, **When** viewed, **Then** each step reflects a real task/event timestamp and status (never a fixed "steps 1–3 are done" placeholder), and the agent's own accent color (US12) is used consistently across its card, its workspace header, and its timeline markers.

---

### User Story 5 — Task Board (Priority: P2)

A status-grouped board (Queued, Running, Waiting, Blocked, Completed, Failed — matching the real, post-US7 `TaskStatus` values) shows every task in the active run(s), each card carrying agent (with its US12 accent color), priority, started time, duration, dependency summary, and its latest event. This is a **read-only adaptation of TradingOS's own existing `KanbanBoard`/`strategy-card` pattern** (`frontend/src/components/strategies/`, currently used for the Strategy lifecycle board) — same column/card shell and `visibleStages`-style column visibility, minus drag-and-drop (task status is system-driven, not human-set by dragging a card).

**Why this priority**: Explicitly required ("organization task board... columns"); no equivalent view exists today (only a flat, unfiltered task list) — but TradingOS already has a proven, tested board pattern one route over, so this is an adaptation, not a from-scratch build.

**Independent Test**: With a run containing tasks in at least four different statuses, open the Task Board and confirm each task appears in exactly the column matching its live `status`, and moves columns in realtime (via the existing WebSocket stream) when its status changes, with no manual refresh.

**Acceptance Scenarios**:

1. **Given** tasks across multiple statuses, **When** the board is viewed, **Then** each task appears in exactly one column matching `Task.status`.
2. **Given** a task transitions status (e.g., `waiting_for_dependency → ready → running → completed`), **When** the transition happens, **Then** the card moves columns live, driven by the existing `organization:events` stream.
3. **Given** a blocked task, **When** its card is viewed, **Then** it shows the same blocked-reason text as the existing `taskStateExplainer`.
4. **Given** more than one active run, **When** the board is viewed, **Then** tasks are filterable by run (default: all active runs).

---

### User Story 6 — Activity Stream explains itself and reads like a real operations log (Priority: P2)

Every event in the live/historical activity feed carries a short, plain-language reason alongside its raw type, reusing the same explanatory logic already used for task cards and decisions (`taskStateExplainer`, `OrganizationalDecision.reason`). Adopting the reference ZIP's tone-tagged event-log pattern, each event's family (`plan.*`, `task.*`, `agent.*`, `dependency.*`, `result.*`, `review.*`, `approval.*`, `ceo.decision.*`) renders with a small, consistent color tag (extending TradingOS's existing state→color convention, not inventing a new palette) so the feed is scannable at a glance, not a flat list of identical-looking rows.

**Why this priority**: Explicit product requirement ("every major status should answer WHY") plus the reference's core lesson that an activity feed should be visually scannable by event family; currently only task cards and decisions explain themselves and every event row looks the same regardless of type.

**Independent Test**: Trigger a `task.waiting_for_dependency` event and confirm the activity stream row includes the same human-readable reason the task card shows for that task, not just the bare event type.

**Acceptance Scenarios**:

1. **Given** any event type that has a corresponding explainer (`task.*`, `dependency.*`, `approval.*`, `ceo.decision.*`), **When** it appears in the Activity Stream, **Then** a plain-language reason string is rendered inline.
2. **Given** an event type with no natural plain-language reason (e.g., a pure informational log), **When** it appears, **Then** it renders without a fabricated explanation rather than a misleading one.
3. **Given** the reason text, **When** compared to the equivalent task-card/decision text for the same underlying state, **Then** they are consistent (single source of truth, not two independently-maintained copies).
4. **Given** events of different families appear in the same feed, **When** viewed, **Then** each renders with a distinct, consistent color tag by family (e.g., `approval.*` always the same tag color), extending TradingOS's existing state-color tokens rather than introducing an unrelated palette.

---

### User Story 7 — CEO delegation and task lifecycle are fully real (Priority: P2)

The CEO's always-injected context tasks (news/sentiment/market/portfolio scaffold) are assigned by capability lookup like the rest of the plan, not by hard-coded agent name. The `TaskStatus` enum contains only states the engine actually produces: `RETRYING` and `ESCALATED` are implemented for real (assigned at the moments described in Verification #6/#7); `AWAITING_APPROVAL`, `WAITING_FOR_AGENT`, and `SUPERSEDED` are removed along with their dead filter references.

**Why this priority**: Closes the last piece of the "genuine dynamic delegation" requirement and prevents the lifecycle/reality mismatch that caused the original C-5 finding from recurring in a new form.

**Independent Test**: Register a second agent declaring the `news_ingestion` capability (test-only fixture); confirm the scaffold now resolves to whichever capable agent `find_by_capability` returns, not unconditionally `news_agent`. Separately, force a task to fail once and retry successfully; confirm its status is observably `RETRYING` during the retry window (not silently `READY`), and force a permanent escalation; confirm status is `ESCALATED`, not `FAILED`, at the moment of escalation.

**Acceptance Scenarios**:

1. **Given** the context scaffold is being assembled for a plan, **When** it resolves each scaffold agent, **Then** it calls `capability_registry.find_by_capability` exactly as the rest of the planner does.
2. **Given** a task fails and is within its retry budget, **When** it is re-queued, **Then** `Task.status == RETRYING` for the duration of the wait/redispatch, transitioning to `RUNNING` only once actually redispatched.
3. **Given** a task escalates to a human/CEO decision rather than exhausting retries or completing, **When** that happens, **Then** `Task.status == ESCALATED`, distinct from `FAILED`.
4. **Given** the enum change, **When** the full test suite and any frontend status-label mapping are checked, **Then** no dead reference to `AWAITING_APPROVAL`/`WAITING_FOR_AGENT`/`SUPERSEDED` remains.

---

### User Story 8 — Per-agent skill/tool grants are enforced (Priority: P3)

An agent can only invoke a skill/tool it has actually been granted (via `AgentSkillMap`), in addition to the existing global enable/disable switch. Operators can view, grant, and revoke these per-agent grants from the Agent Settings UI.

**Why this priority**: The backend catalog and API already exist; this closes the enforcement and UI gaps so the feature is not "console-only theater" (the same defect class as US2).

**Independent Test**: Grant `fetch_nse_sector_data` to `market_analyst_agent` only; confirm `market_analyst_agent` can invoke it and a different agent without the grant cannot (a clear, catchable error, not an uncaught exception — note the existing `_try_skill` catch-gap for `SkillDisabledError` should be closed for the new `SkillNotGrantedError` at the same time).

**Acceptance Scenarios**:

1. **Given** `AgentSkillMap` contains a grant for `(agent_x, skill_y)`, **When** `agent_x` invokes `skill_y`, **Then** it succeeds (assuming the skill is also globally enabled).
2. **Given** no grant row for `(agent_z, skill_y)`, **When** `agent_z` attempts to invoke `skill_y`, **Then** it is refused with a specific, caught `SkillNotGrantedError`, not a generic uncaught exception.
3. **Given** the migration cutover, **When** it runs, **Then** every `(agent, skill)` pair actually exercised in the prior 30 days is seeded as granted, so no currently-working agent breaks.
4. **Given** the Agent Settings UI, **When** an SA views an agent, **Then** they can see, grant, and revoke its skill grants, gated the same way prompt/provider changes are.

---

### User Story 9 — Prompt activation requires explicit confirmation (Priority: P3)

Activating a prompt version requires the diff (current active vs. the version being activated) to have been rendered and an explicit confirmation action taken — a single click on "Activate" alone is no longer sufficient.

**Why this priority**: Closes the remaining half of audit finding C-4; small, isolated, high-value for a privileged operation.

**Independent Test**: Attempt to activate a version without opening its diff; confirm the action is blocked or requires an additional explicit step; open the diff, confirm, and confirm activation proceeds and is audited as before.

**Acceptance Scenarios**:

1. **Given** a version has not been diffed against the current active version in the current session, **When** "Activate" is clicked, **Then** the diff view opens instead of activating immediately, requiring a second explicit confirm.
2. **Given** the diff has been viewed and confirmed, **When** activation proceeds, **Then** the existing audit trail (actor, before/after state) is unchanged.
3. **Given** rollback (which reuses the same activation path), **When** invoked, **Then** the same confirm-after-diff requirement applies.

---

### User Story 10 — Run history is browsable (Priority: P3)

A dedicated, paginated, filterable (by status, date range) list of past organization runs exists, backed by the already-real `status`/`limit` server-side filter (extended with `offset`/cursor pagination).

**Why this priority**: Currently capped at an unpaginated, unfiltered most-recent-20 view; low complexity, real operational value once run volume grows.

**Independent Test**: With more than 50 historical runs, confirm the list can page past the current 50-row cap and can be filtered to, e.g., only `failed` runs.

**Acceptance Scenarios**:

1. **Given** more runs than one page, **When** the operator pages forward, **Then** additional runs load without duplicating or skipping rows.
2. **Given** a status filter is applied, **When** results are returned, **Then** only matching runs appear, server-side (not client-truncated).
3. **Given** a run in the list, **When** clicked, **Then** it opens the existing run detail workspace unchanged.

---

### User Story 11 — Analytics and audit-reference completeness (Priority: P3)

Agent analytics additionally shows retry counts and escalation counts per agent (token/cost usage is deferred — see Assumptions). `OrganizationalDecision`, `ResultArtefact`, and `Task` rows carry a real `audit_reference` pointing at the `AuditLog` entry their creation/transition produced.

**Why this priority**: Closes two small, independent, low-risk completeness gaps; grouped together as both are "the data exists, the last write is missing."

**Independent Test**: Force a task retry and an escalation; confirm both are reflected in the agent's analytics counts. Record a decision; confirm `OrganizationalDecision.audit_reference` resolves to a real, matching `AuditLog` row.

**Acceptance Scenarios**:

1. **Given** an agent with retried/escalated tasks in the analytics window, **When** its analytics are viewed, **Then** retry and escalation counts are shown, computed from real `Task` rows.
2. **Given** `events.emit(..., audited=True)`, **When** it returns, **Then** the caller receives the created `AuditLog` id and stores it on the domain row's `audit_reference`.
3. **Given** any `OrganizationalDecision`/`ResultArtefact`/`Task` with a non-null `audit_reference`, **When** resolved, **Then** it points at a real, matching `AuditLog` entry (not a dangling FK).

---

### User Story 12 — Agent Fleet: a card-based, department-grouped live roster (Priority: P2)

Add a live **Agent Fleet** view to the console's **Organization** tab, next to the CEO Workspace (US13) — a card grid, grouped by real department (Executive, Market Intelligence, Research, Quant, Risk & Governance, Portfolio, Operations — from the existing `capability_registry`), each card showing agent identity (name, a distinct per-agent accent color, icon), real live status, current task, health, and resolved provider/model (US2). This is additive to, not a replacement of, the existing admin enable/disable table, which stays exactly where it already is today — in its own separate "Agents & Legacy Graph" tab — as a distinct "manage" affordance, untouched by this story.

**Why this priority**: Explicit requirement ("agent cards," "agent hierarchy," department grouping); today agent identity is purely textual and there is no live, at-a-glance roster — only an admin toggle table.

**Independent Test**: With ≥2 agents active in different departments, open the Fleet view and confirm cards are grouped by their real department, each shows a distinct accent color consistently reused in that agent's own workspace (US4), and status/current-task/health reflect live backend state (verified by forcing a status change and confirming the card updates without refresh).

**Acceptance Scenarios**:

1. **Given** the Fleet view is open, **When** viewed, **Then** agents are grouped under their real department headings, sourced from `capability_registry`, not a hardcoded list.
2. **Given** an agent's status changes (e.g., idle → running), **When** viewed, **Then** the card updates live via the existing event stream, with no manual refresh.
3. **Given** two different agents, **When** their cards are compared, **Then** each has a distinct, consistent accent color that also appears in that agent's own workspace (US4) header and timeline.
4. **Given** the existing admin enable/disable table, **When** the Fleet ships, **Then** the admin table remains accessible and functional, unchanged.

---

### User Story 13 — CEO Workspace: a real operational deep-dive (Priority: P2)

Elevate `OrganizationOverview.tsx` from an admin-panel-style status page into a rich **CEO Workspace**: current objective, organization/CEO status, current phase, delegation summary (who's been assigned what), running/waiting/blocked/completed/failed agent counts, recent decisions, pending approvals, and next action — plus a KPI tile row (active agents, tasks completed today, average task duration, success rate — real `NumberTicker`-driven numbers, no fabricated "token efficiency") and a real, event-sourced **operational narration feed**: plain-language strings like "Delegating market analysis," "Waiting for Risk Manager," "Market and Sentiment analysis conflict detected," each derived from a real `OrganizationalEvent`'s type + reason (US6) — never a private model chain-of-thought, never fabricated.

**Why this priority**: Explicit requirement ("CEO workspace," "operational activity... do not expose hidden chain-of-thought"); today's Organization Overview shows real status but reads as an admin panel, not a command-center view of what the CEO is actually doing right now.

**Independent Test**: During an active run, open the CEO Workspace and confirm the narration feed's most recent line matches the most recent real `OrganizationalEvent` for that run (by cross-checking the raw event), confirm the KPI tiles match real counts obtainable from the analytics/runs endpoints, and confirm no narration line appears that doesn't correspond to a real event.

**Acceptance Scenarios**:

1. **Given** an active run, **When** the CEO Workspace is viewed, **Then** current objective, phase, delegation summary, and next action are shown, all sourced from real `OrganizationRun`/`OrganizationalPlan`/`Task` state.
2. **Given** a new `OrganizationalEvent` is emitted for the CEO's own actions (planning, delegating, deciding), **When** it occurs, **Then** a corresponding narration line appears in the feed within the existing live-update budget.
3. **Given** the KPI tile row, **When** viewed, **Then** every number is computed from a real query (active agent count, tasks completed today, average duration, success rate) — never a placeholder or a fabricated "token efficiency" metric (explicitly deferred per this spec's existing Assumptions).
4. **Given** no active run, **When** the CEO Workspace is viewed, **Then** it honestly shows an idle/no-objective state, not stale data from a prior run.

---

### User Story 14 — Dependency graph is interactive and animates real state (Priority: P2)

Upgrade the existing, already-real `OrgTaskGraph.tsx` (which already computes true topological depth and real dependency `state` from live data) with pan/zoom navigation and animated edge-activation the moment a real `dependency.satisfied` event is observed on the live stream — not a cosmetic replay, an actual reflection of the event as it happens.

**Why this priority**: Explicit requirement ("dependency graph," "animations should indicate actual state... dependency satisfied → line activates"); the underlying data is already real (Verification #11) but the rendering is a fixed, non-interactive SVG today, understating work that's already done on the backend.

**Independent Test**: With a run in progress, watch a dependency's prerequisite complete; confirm the corresponding edge visibly activates (color/animation change) within the existing live-update budget, driven by the real `dependency.satisfied` event, not a fixed timer or replay. Confirm the graph can be panned and zoomed without losing its real layout.

**Acceptance Scenarios**:

1. **Given** a dependency graph with more nodes than fit on screen, **When** viewed, **Then** the operator can pan and zoom without the graph's layout breaking or nodes overlapping.
2. **Given** a prerequisite task completes, **When** its dependency is marked satisfied, **Then** the corresponding edge animates to an "active" state driven by the real `dependency.satisfied` event, not a fixed delay.
3. **Given** the graph, **When** compared against `GET .../dependencies`, **Then** every rendered node/edge matches real backend state exactly (no cosmetic-only nodes/edges).

---

## Requirements *(summary — full FR-xxx numbering deferred to plan.md/tasks.md)*

- **Governance**: no code path may transition a strategy to Paper Trading without a decided `ApprovalRequest` (US1). Per-agent prompt activation requires a viewed-diff confirmation (US9).
- **Fidelity**: a configured per-agent provider/model or skill grant must actually affect runtime behavior, never be recorded-but-inert (US2, US8).
- **Observability**: every agent-to-agent artefact exchange is a first-class handoff (US3); every agent is inspectable through one complete, context-preserving, reference-quality two-panel workspace (US4); work is visible by status (US5); every event explains itself and is visually scannable by type (US6); history is browsable (US10); analytics and audit references are complete (US11).
- **Correctness**: delegation is capability-based everywhere, and the task lifecycle enum contains only reachable states (US7).
- **Presentation / IA**: the console adopts the reference ZIP's agent-card, agent-workspace, and CEO-narration information architecture, built from TradingOS's own existing design tokens, component primitives, and motion vocabulary — never the reference's mocked data or its own app shell (US12, US13, US14).
- **No regressions**: `AUTO` routing remains byte-identical (US2 AC2); non-`PaperTrading` promote transitions are unchanged (US1 AC5); the existing Strategy `KanbanBoard` and admin Agent Registry remain functional, unmodified in their own domains (US5, US12); all existing passing tests continue to pass.

## Success Criteria

- **SC-001**: Zero code paths can move a strategy into `PaperTrading` without a matching `approved` `ApprovalRequest` — enforced by a test that specifically targets the `/promote` bypass.
- **SC-002**: 100% of `complete()` call sites in `src/agents/nodes/` and `src/orchestration/agent_invoker.py` pass `agent_name=` — enforced by a repo-wide static check, not spot-checked.
- **SC-003**: The Agent Workspace renders real (or honestly-empty/interim-labeled) data for all 12 required sections, in the reference-inspired two-panel layout with agent-color identity, for at least one graph-node and one non-graph agent, verified in a Cypress test.
- **SC-004**: A Task Board, a Handoff inspector, and an interactive Dependency Graph exist and reflect live backend state within the existing ~2s console update budget.
- **SC-005**: No `TaskStatus` enum value exists that no code path ever assigns.
- **SC-006**: All existing `001-ceo-led-trading-org` tests remain green; no regression in AUTO routing, dependency waiting, parallel execution, or conflict detection.
- **SC-007**: The Agent Fleet, CEO Workspace, and every new component built for this feature use only TradingOS's existing design tokens, component primitives (`Card`, `Badge`, `IconBadge`, `Sheet`, `Dialog`, `NumberTicker`), and `framer-motion` presets — zero new animation, theming, or component-library infrastructure introduced, verified by code review against `plan.md`'s Project Structure.
- **SC-008**: Every string presented as CEO or agent "activity" (CEO Workspace narration, Agent Workspace timeline, Activity Stream) resolves to a real, queryable `OrganizationalEvent`/`Task`/`OrganizationalDecision` row — none is generated client-side without a backing event.

## Assumptions

- Token/cost usage in analytics is **not** included in US11 — it requires per-provider cost-metadata plumbing (not confirmed available from all configured providers) and is deferred to a future spec if wanted; the reference ZIP's "token efficiency" KPI tile (US13) is likewise not adopted for the same reason.
- The reference ZIP's visual language is adapted to TradingOS's existing design system, not cloned pixel-for-pixel or introduced as a parallel one — per the Scope Correction and Reference ZIP Analysis above.
- TradingOS's existing whole-app shell (top nav, account-scope switcher, command palette, notification center) is retained unchanged; the reference's own sidebar shell and four non-functional placeholder tabs are not adopted.
- No new datastore, message broker, frontend framework, component library, or animation system is introduced; every gap above is closed by extending existing modules (`src/orchestration/`, `src/agents/`, `frontend/src/components/console/`, `frontend/src/components/agent-settings/`, `frontend/src/components/strategies/kanban-board.tsx` as the Task Board's adaptation source, `frontend/src/lib/motion.ts` as the sole animation vocabulary).
