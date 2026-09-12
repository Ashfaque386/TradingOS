# Implementation Plan: Agent Organization Hardening & Console Completion

**Branch**: `002-agent-organization-hardening` | **Date**: 2026-09-12 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/002-agent-organization-hardening/spec.md`

## Summary

`001-ceo-led-trading-org` built the real thing — a genuine CEO planner, task engine, dependency resolver, artefact/event/decision model, and live console. This feature does not rebuild any of that backend; it closes eleven verified gaps found by re-auditing the shipped system against its own requirements (US1–US11), **and**, per the 2026-09-12 Scope Correction in spec.md, redesigns the console's presentation layer using the supplied reference ZIP as the primary UX/UI/interaction baseline (US4/US5/US6 expanded, plus three new stories US12–US14) — while extending, never replacing, TradingOS's own already-real backend, design tokens, component library, and motion system.

Backend-hardening stories: one live governance bypass (US1), one inert-but-fully-built feature (US2, provider/model override), one missing first-class concept (US3, handoffs — now also a UI surface), two missing views (US5 Task Board, US10 run history), one correctness/consistency cleanup (US7), one unenforced-but-cataloged feature (US8, skills), two small completeness items (US9 confirm-before-activate, US11 analytics/audit-reference). Presentation-layer redesign stories: US4 (agent workspace, rebuilt as the reference's two-panel deep-dive IA), US6 (activity stream, tone-tagged), US12 (Agent Fleet — card-based, department-grouped roster), US13 (CEO Workspace — narration-driven deep-dive), US14 (Dependency graph interactivity).

**Technical approach**: every backend change is an extension of an existing module — no new service, datastore, or framework. Every frontend change composes TradingOS's own existing design tokens, component primitives, and motion vocabulary — no new component library, theming system, or animation framework (see "Design System Constraints" below).

- **US1** (`strategies.py::promote`): add one guard clause consulting `ApprovalRequest` state before allowing `to_status == "PaperTrading"`; emit the missing `approval.requested` event from the existing `_open_paper_approval_request` call site.
- **US2** (`llm_router.py` callers): thread `agent_name=` through every real call site in `src/agents/nodes/*.py`, `src/orchestration/planner.py`, `src/orchestration/agent_invoker.py`. No change to `llm_router.complete()` itself (the resolution logic is already correct) or to `agent_config.py` (already correct) — this is purely "finish wiring the last mile."
- **US3** (handoffs): add a read-side query/view (`src/orchestration/handoffs.py`) that derives handoff rows from existing `ResultArtefact.consumed_by_task_ids` + `Task.received_inputs` + `Task.assigned_agent` — no new table, since the source data is already fully populated and this is presentation, not new state. Expose `GET /organization/runs/{id}/handoffs`.
- **US4** (agent workspace): extend the existing `GET /agents/{id}/activity` response with the missing fields (dependencies, waiting reason, inputs, tools/skills, resolved provider/model, errors/retries, handoffs, downstream consumers, audit refs) by composing already-existing service functions (`dependency_resolver`, `capability_registry`, US2's provenance, US3's handoffs, `audit` lookups) — no new backend concept, just a richer existing endpoint. Frontend: thread `?runId=&taskId=` through the agent link and `AgentDetail.tsx`'s query.
- **US5** (Task Board): new frontend component only, grouping the existing `GET .../tasks` response by `status` client-side; no backend change.
- **US6** (Activity Stream explanations): factor `taskStateExplainer`-equivalent logic into a shared function usable by both task cards and the event feed (`frontend/src/lib/eventExplainer.ts`), or extend the event payload server-side with a `reason` field at emit time for the event types that already have one available (dependency waiting reason, decision reason) — prefer the server-side option where the reason is already computed at emit time (near-zero marginal cost), fall back to shared frontend logic otherwise.
- **US7** (delegation/enum correctness): `ensure_research_scaffold` calls `capability_registry.find_by_capability` instead of hard-coded names; `enums.py` drops three unused `TaskStatus` values; `task_engine.py` assigns `RETRYING`/`ESCALATED` at the exact points already identified in Verification #6/#7 (the code branches already exist — this is changing what status they set, not adding new branches).
- **US8** (skill enforcement): `SkillRegistry.execute()` gains an optional `agent_name` parameter; when supplied, checks `AgentSkillMap` before proceeding (skips the check if `agent_name` is `None`, preserving today's behavior for any call site not yet updated — but all real call sites are updated as part of this story, matching the SC-002 approach from US2). Frontend: new grant/revoke panel under `agent-settings/`.
- **US9** (confirm-before-activate): frontend-only — `PromptVersionHistory.tsx` requires the diff to have been opened (tracked in local component state) before enabling the Activate action; no backend change (the audit trail is already correct).
- **US10** (run history): extend `GET /organization/runs` with `offset`/cursor support (small addition to an existing query); new frontend route `console/runs/page.tsx`.
- **US11** (analytics + audit-reference): `src/agents/analytics.py` adds retry/escalation aggregates from existing `Task` columns; `events.emit()` returns the created `AuditLog` id so the three call sites (`decisions.py::record_decision`, `artefact_store.py::persist_artefact`, `task_engine.py`'s task-transition writes) can store it back onto `audit_reference`.
- **US12** (Agent Fleet): new `AgentFleet.tsx`, added to the console's Organization tab next to the CEO Workspace (US13) — a `Card`-grid grouped by real department, using `staggerContainer`/`fadeUp` for entrance and a new, additive `--agent-color-<slug>` CSS custom property per agent (assigned deterministically, e.g. hashed from `agent_id`, or a small fixed palette cycling by department — decided in T-phase) — layered on top of, never replacing, the existing `--color-up`/`--color-down`/`--color-warn` tokens. **Confirmed zero backend change**: `src/api/routers/agents.py`'s existing `AgentRegistryEntry` response (API-025, already consumed by `agent-registry.tsx`) already serializes `department`, `capabilities`, `is_llm_backed`, `health`, `live_status` — no new endpoint or field needed. The existing admin `AgentRegistry` table is untouched, in its own separate "Agents & Legacy Graph" tab.
- **US13** (CEO Workspace): rewrite `OrganizationOverview.tsx`'s presentation (not its data-fetching, which is already real) into the deep-dive layout, adding a `NumberTicker`-driven KPI tile row and an operational-narration feed that filters the same event stream US6 already renders, framed as CEO-level narration (a small mapping from `event_type` + US6's `reason` to a short present-tense sentence — e.g. `task.dispatched` + `agent=market_analyst_agent` → "Delegating market analysis to Market Analyst"). No new backend endpoint; narration is a frontend presentation of existing real events.
- **US14** (Dependency graph interactivity): `OrgTaskGraph.tsx` gains pan/zoom (a small viewport-transform wrapper, no new charting library) and an edge-activation animation triggered by the existing `dependency.satisfied` event already arriving over `useOrganizationStream` — purely a rendering change against already-real data.

No new dependencies. No new datastore. No change to LangGraph, the deterministic risk/compliance/kill-switch engines, or the core task-engine scheduling algorithm (all verified working in the Current-State Verification). No new frontend component library, theming system, or animation framework — see Design System Constraints below.

## Design System Constraints (binding for US4, US5, US6, US12, US13, US14)

Per spec.md's Reference ZIP Analysis, TradingOS's existing frontend foundations are independently verified as real, deliberate, and in most respects more capable than the reference demo's own. Every presentation-layer story in this feature **must**:

- Use existing design tokens only (`frontend/src/app/globals.css`'s CSS custom properties) for color/spacing/radius/typography. The one net-new token category is a per-agent identity color (US12), which is additive and must never redefine or be confused with `--color-up`/`--color-down`/`--color-warn` (explicitly protected as P&L-only colors by an existing code comment).
- Use existing component primitives (`Card`, `Badge`, `IconBadge`, `Dialog`, `Sheet`, `NumberTicker`, `Tabs`) from `frontend/src/components/ui/` rather than introducing new ones, except where a genuinely new composite is needed (`AgentFleet.tsx`, `TaskBoard.tsx`, `HandoffPanel.tsx` — all composed from existing primitives, not new primitives themselves).
- Use only the named motion presets already defined in `frontend/src/lib/motion.ts` (`fadeUp`, `scaleIn`, `slideUp`, `staggerContainer`/`staggerItem`, `floatingIcon`) — no new framer-motion variants invented ad hoc.
- Adapt, not duplicate, the existing `frontend/src/components/strategies/kanban-board.tsx` + `strategy-card.tsx` pattern for the Task Board (US5) — a read-only variant (no drag-and-drop) reusing the same column-shell approach.
- Extend, not replace, the existing task/node state→color convention (`graph-flowchart.tsx`'s `STATE_STYLES`, `OrgTaskGraph.tsx`'s satisfied/unsatisfied coloring) for any new status-driven coloring.
- Leave TradingOS's whole-app shell (`AppShell`, `TopNav`, the other 9 peer routes) completely untouched — every change in this section is scoped to content *inside* `/console`.

## Technical Context

**Language/Version**: Python 3.12 (backend); TypeScript 5 / Node 20 (frontend, Next.js App Router) — unchanged from `001-ceo-led-trading-org`.

**Primary Dependencies**: all existing (FastAPI, SQLAlchemy 2.0, Alembic, LangGraph, LiteLLM router, Redis, Qdrant, Casbin policy engine, React Query, Zustand, the `diff` package already used by `PromptDiff.tsx`). No new dependency anticipated for any of the eleven stories.

**Storage**:
- **Postgres**: one new nullable column, `Task.audit_reference` if not already present (verify against `src/models/orchestration.py` — data-model.md confirms it exists as a declared-but-unwritten column, so likely no migration needed at all for US11's audit-reference half; confirm during T-phase). No new tables for handoffs (US3) — derived, not stored, unless read-performance during implementation proves a materialized approach is needed, in which case a single `handoffs` read-model table populated in the same transaction as `mark_consumed` is the fallback (documented here so it isn't a surprise mid-implementation, decided empirically in Phase 3 below).
- **Redis**: no new channel — `approval.requested` (US1) and any new event-adjacent reason fields (US6) reuse the existing `organization:events` channel.
- **Qdrant**: untouched.

**Testing**: `pytest` (unit + integration, matching `001-ceo-led-trading-org`'s pattern exactly — reuse `tests/orchestration_helpers.py`); Cypress for every new/changed frontend surface (Agent Workspace, Task Board, Activity Stream reasons, Run History, Agent Fleet, CEO Workspace, Dependency Graph interactivity). All via `docker compose run --rm app ...` (constitution II, unchanged).

**Target Platform**: unchanged — single hardened Docker Compose host.

**Performance Goals**: no new performance goal; US5/US10 must not regress the existing ~2s live-update budget (SC-007 of `001-ceo-led-trading-org`, still binding here).

**Constraints** (all inherited unchanged from `001-ceo-led-trading-org`'s constitution check, re-affirmed below):
- The deterministic risk engine, kill switch, compliance checks, RBAC, and audit chain retain final authority; none of the eleven stories touches them except to *close* a bypass (US1) or *complete* their reference-linking (US11) — never to weaken them.
- No code path may place a live order or move real funds automatically — unaffected by this feature.
- All execution in Docker; no host Python.
- `mypy --strict` clean; ruff/black clean.

**Scale/Scope**: 14 user stories; 0 new tables (1 possible fallback table for US3, decided empirically); ~2 new/extended REST endpoints (`GET .../handoffs`, extended `GET .../activity` and `GET /organization/runs`) — US12/US13/US14 add **zero** new endpoints (pure presentation over already-real data); ~8 new/changed frontend routes or major components (Agent Workspace rewrite, Task Board, Run History list, Skill grant panel, Agent Fleet, CEO Workspace rewrite, Dependency Graph interactivity, tone-tagged Activity Stream); 1 enum change; 1 repo-wide "every `complete()` call site passes `agent_name`" mechanical change; 1 new additive design token category (per-agent identity color).

## Constitution Check

*GATE: must pass before Phase 0 (re-checked below is trivial since this feature closes gaps rather than adding new surface area).*

| # | Principle | Assessment | Gate |
|---|---|---|---|
| I | Spec-Driven & Traceable | Every user story here traces to a specific, evidenced verification finding (spec.md's Current-State Verification table) rather than a speculative requirement, and `tasks.md` carries task→story→test links. Full principle compliance additionally requires (a) a citation into `Project Document and BluePrint/` and (b) a roadmap epic recorded in `TradingOS_ERDTM.xlsx` — both are now satisfied: spec.md's new "Constitution Traceability" section cites `Phase_7_Frontend_Architecture.md` §6 / `TradingOS_Master_Blueprint.md`'s Agent Console section as the Blueprint requirement, and reserves roadmap epic `REL-097`; `tasks.md` T058 performs the actual roadmap/ERDTM recording as a delivery task (matching `001-ceo-led-trading-org`'s own precedent for this principle). | **PASS** |
| II | Docker-Only Execution | Unchanged — all work via `docker compose run --rm app ...` / Cypress container. | **PASS** |
| III | Quality Gates Non-Negotiable | Same gate set as `001-ceo-led-trading-org` (ruff, black, mypy --strict, bandit, gitleaks, pip-audit, alembic upgrade head, pytest --cov, Cypress) must stay green; US1 and US2 each add a regression test specifically shaped to prevent recurrence (a bypass test, a call-site-coverage test). | **PASS** |
| IV | Safety-Critical Trading Controls | US1 *tightens* a governance gate (closes a bypass); it does not add any new automated trading action and does not touch the deterministic risk/compliance/kill-switch code. US8 (skill enforcement) is additive-restrictive (can only refuse a previously-unchecked call, never grant new capability). | **PASS** |
| V | Module Storage Ownership | US3's fallback materialized table (if needed) would live in `src/orchestration/` + `src/models/orchestration.py`, following the exact existing ownership pattern — no cross-module direct store access introduced. | **PASS** |
| VI | Real Integrations, Honest Status | This entire feature exists *because* of this principle — US2 and US8 close two "recorded but has no real effect" gaps that themselves violate it today. | **PASS** |
| VII | Secrets Never in Source | Untouched — no new secret-adjacent surface. | **PASS** |

**Result: PASS — no violations.**

## Project Structure

### Documentation (this feature)

```text
specs/002-agent-organization-hardening/
├── plan.md              # This file
├── spec.md              # Feature spec (Current-State Verification + Audit Gap Analysis + 11 user stories)
├── data-model.md         # Handoff derivation + audit_reference write-path notes (no new tables unless Phase 3 proves otherwise)
└── tasks.md              # Phased, dependency-ordered task list
```

*(`research.md`, `contracts/`, `quickstart.md`, and `checklists/` are intentionally not produced as separate files for this hardening feature — the Current-State Verification in spec.md already serves research.md's purpose (documented technical decisions with evidence), and the endpoint-level contracts are small enough to specify inline in tasks.md per task. If implementation later reveals a need for formal contracts docs, add them under this same folder without renumbering.)*

### Source Code (repository root, changes only — full tree unchanged from `001-ceo-led-trading-org`)

```text
TradingOS/
├── src/
│   ├── orchestration/
│   │   ├── handoffs.py                  # NEW — US3: derive handoff rows from existing artefact/task data
│   │   ├── task_engine.py               # CHANGED — US7: assign RETRYING/ESCALATED; US11: capture audit_reference
│   │   ├── decisions.py                 # CHANGED — US11: capture audit_reference from events.emit()
│   │   ├── artefact_store.py            # CHANGED — US11: capture audit_reference
│   │   ├── events.py                    # CHANGED — US1: approval.requested emission point; US11: return AuditLog id
│   │   ├── planner.py                   # CHANGED — US7: scaffold resolves agents via capability_registry
│   │   ├── enums.py                     # CHANGED — US7: drop AWAITING_APPROVAL/WAITING_FOR_AGENT/SUPERSEDED
│   │   └── agent_invoker.py             # CHANGED — US2: pass agent_name to complete(); US8: pass agent_name to skill execute()
│   ├── agents/
│   │   ├── nodes/*.py                   # CHANGED (every file) — US2: pass agent_name=<slug> to complete()
│   │   ├── llm_router.py                # UNCHANGED (already correct — verified)
│   │   ├── tools/registry.py            # CHANGED — US8: enforce AgentSkillMap when agent_name supplied
│   │   └── analytics.py                 # CHANGED — US11: retry/escalation aggregates
│   ├── api/routers/
│   │   ├── strategies.py                # CHANGED — US1: guard /promote against approval state
│   │   ├── organization.py              # CHANGED — US3: GET .../handoffs; US10: offset/cursor on GET /runs
│   │   └── agents.py                    # CHANGED — US4: enrich GET /agents/{id}/activity
├── alembic/versions/
│   └── <rev>_task_status_cleanup.py     # NEW (if needed) — drop the 3 unused TaskStatus enum values from any CHECK constraint
└── frontend/src/
    ├── app/globals.css                  # CHANGED — US12: add additive --agent-color-* token category
    ├── components/console/
    │   ├── AgentDetail.tsx              # REWRITTEN — US4: two-panel deep-dive IA, all 12 sections, context-aware, agent-color identity
    │   ├── AgentFleet.tsx               # NEW — US12: department-grouped card grid, reused as the in-workspace switcher strip (US4)
    │   ├── OrganizationOverview.tsx     # REWRITTEN (presentation only) — US13: CEO Workspace deep-dive, KPI tiles, narration feed
    │   ├── OrgTaskGraph.tsx             # CHANGED — US14: pan/zoom + real edge-activation animation
    │   ├── TaskBoard.tsx                # NEW — US5, adapted from components/strategies/kanban-board.tsx (read-only)
    │   ├── ActivityStream.tsx           # CHANGED — US6: render reason + tone-tagged event-family colors
    │   ├── HandoffPanel.tsx             # NEW — US3, reused inside AgentDetail's right panel (US4)
    │   └── panels.tsx                   # CHANGED — minor, if run-history filter lives here
    ├── components/agent-settings/
    │   ├── PromptVersionHistory.tsx     # CHANGED — US9: confirm-after-diff gate
    │   └── SkillGrantPanel.tsx          # NEW — US8
    ├── lib/
    │   ├── eventExplainer.ts            # NEW/extended — US6 shared reason logic, reused by US13's narration mapping
    │   └── agentColor.ts                # NEW — US12: deterministic agent → accent-color assignment, single source of truth reused by US4/US5
    ├── app/(app)/console/
    │   ├── runs/page.tsx                # NEW — US10: run history list
    │   └── agents/[agentId]/page.tsx    # CHANGED — US4: read runId/taskId query params
    └── lib/api.ts                        # CHANGED — new endpoint bindings
```

Note: `components/strategies/kanban-board.tsx` and `strategy-card.tsx` (US5's adaptation source) are **read**, not modified — the Task Board is a new, separate read-only component in `components/console/`, not a shared/forked copy that could regress the Strategy lifecycle board.

## Phasing (see tasks.md for the task-level breakdown)

1. **Phase 1 — Governance-critical (US1, US2)**: close the live bypass and the inert override. Ship independently; highest risk-reduction per unit effort.
2. **Phase 2 — Observability & presentation core (US3, US12, US4, US5, US6, US14)**: the actual "agent console completion + redesign" the product brief centers on. Recommended internal order: **US3 (handoffs data) → US12 (Agent Fleet, needed as the switcher-strip source) → US4 (Agent Workspace, consumes both) → US5 (Task Board) → US6 (Activity Stream tone-tagging) → US14 (Dependency graph interactivity, independent of the others, can run in parallel)**. US4 depends on US3 (handoffs) and US2 (resolved provider/model) for two of its data sections, and on US12 for its Fleet-strip switcher — sequence accordingly. US4 additionally has a *soft* dependency on US8 (Phase 4, tools/skills grants) and US11 (Phase 5, populated audit references) for its remaining two data sections; US4 does not wait for these — per spec.md US4's Dependency note and AC5, it ships with those two sections in an explicit "not yet enforced"/"not yet linked" state and upgrades automatically once US8/US11 land, with no rework to US4's own code.
3. **Phase 2b — CEO Workspace (US13)**: depends on US6's `reason` field (narration mapping reuses it) — sequence after US6 within Phase 2.
4. **Phase 3 — Correctness cleanup (US7)**: enum change touches task-engine internals; do this once US4/US5 already consume `TaskStatus` so their column/status mappings are updated in the same pass rather than twice.
5. **Phase 4 — Settings hardening (US8, US9)**: independent of Phases 1–3; can run in parallel with them.
6. **Phase 5 — Polish (US10, US11)**: lowest risk, most independent; last.

Every phase ends with its own story's independent test green before the next begins, matching `001-ceo-led-trading-org`'s own delivery discipline.
