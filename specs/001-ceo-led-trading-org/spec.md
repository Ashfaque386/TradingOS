# Feature Specification: CEO-Led AI Trading Organization

**Feature Branch**: `001-ceo-led-trading-org`

**Created**: 2026-09-10

**Status**: Draft

**Input**: User description: "Transform the existing TradingOS application from a fixed sequential agent workflow (plus isolated non-graph agents) into a CEO-led AI trading organization: the owner gives an objective, a CEO agent turns it into a dynamic organizational plan, specialist agents execute — independent work in parallel, dependent work waiting for its inputs — agents collaborate and escalate, the CEO synthesizes, and humans intervene only at defined governance points. Includes a redesigned Organization Command Center console, a dedicated per-agent Settings area (prompt version management + provider/model selection with an AUTO default), real (pre-transition) human approval, integration of the currently-disconnected News/Sentiment/Portfolio agents, data-freshness awareness, agent-first ad-hoc analysis, and omni-channel objectives reaching the CEO. Existing safety architecture (deterministic risk engine supremacy, kill switch, compliance, RBAC, broker controls, audit) must be preserved and never bypassed. The existing LangGraph / LLM router / SkillRegistry / Qdrant / Postgres / Redis / sandbox / risk engine / compliance / audit foundation must be reused, not rewritten. Audit report `docs/audit-2026-09.md` (findings BUG-A … BUG-I plus P0–P3 items) is the implementation baseline."

---

## Overview

TradingOS today runs one fixed research pipeline (13 LangGraph nodes) and a second, loosely-coupled tier of scheduled agents whose outputs nothing consumes. This feature changes the operating model — not the technology stack — so the product behaves like a **professional AI trading firm the owner has hired**: the owner states an objective, and a CEO agent organises the work across departments, running what can run in parallel, holding what must wait, reconciling disagreements, and reporting progress through a live command centre. Deterministic safety controls and human governance are unchanged and remain supreme.

This is a large transformation delivered through **independently valuable slices**. Each user story below is a shippable increment: implementing only US1–US4 already yields a genuinely agent-orchestrated research organisation; the console and settings slices raise it to a premium operations product.

**Out of scope for this spec (belongs to `/speckit-plan` and later phases):** the 28-document `/spec-kit/tradingos/` tree, architecture-delta diagrams, database migration DDL, endpoint-level API contracts, frontend component trees, and the 16-phase implementation roadmap. Those are design/plan artefacts, not product requirements, and are produced after this specification is validated.

---

## Clarifications

### Session 2026-09-10

- Q: Which existing RBAC role(s) may give the human approval that transitions a new strategy from pending into Paper Trading? → A: `SystemAdministrator` and `PortfolioManager` only (mirrors the existing Paper→Live promote gate).
- Q: If the application restarts while an organization run is in progress, what must happen to that run? → A: It resumes automatically from the last completed task/checkpoint; already-finished tasks and their artefacts are not re-run.
- Q: Can more than one organization run be active at the same time, and is there a cap? → A: Yes — up to a small fixed, configurable number run concurrently (default 3); further objectives queue.
- Q: Which existing RBAC role(s) may change an agent's configuration — activating a prompt version, and setting a custom AI provider/model? → A: `SystemAdministrator` only (for both prompt-version activation/rollback and provider/model changes).
- Q: Does the per-agent provider/model override apply to every agent, or only to agents that actually make an LLM call? → A: Only LLM-backed agents show a provider/model selector; deterministic agents show "no model — deterministic" and no picker.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - CEO turns an objective into a dynamic organizational plan (Priority: P1)

The owner (or a schedule, or an omni-channel message) states an objective in plain language — e.g. *"Find low-risk swing opportunities for tomorrow."* The CEO agent classifies the objective, decides which departments and specialist agents are relevant, and produces an **Organizational Plan**: a set of tasks, each assigned to an agent, with declared dependencies, priorities, expected outputs, applicable constraints, and any safety/approval requirements. The plan is generated per objective — it is not a hard-coded chain — and is recorded so it can be inspected and audited.

**Why this priority**: Nothing else in the transformation is possible without a plan object. It is the organisation's operating unit and the foundation every other slice builds on. It directly addresses the audit findings that the CEO currently emits a directive consumed linearly and that no general-purpose task/plan model exists.

**Independent Test**: Submit three materially different objectives and confirm the CEO produces three different plans, each with a task list, per-task agent assignment, and a dependency graph that is acyclic and references only agents that exist; confirm the plan and its tasks are persisted and appear in the audit trail; confirm an objective the organisation cannot serve (no capable agent) produces an explicit "cannot plan" outcome rather than an empty or fabricated plan.

**Acceptance Scenarios**:

1. **Given** the owner submits "prepare tomorrow's trading research", **When** the CEO plans, **Then** an Organizational Plan is created containing at least the market-intelligence, research, quant, and risk/governance tasks with dependencies declared, and a plan-created event and audit entry are written.
2. **Given** an objective that only requires market analysis, **When** the CEO plans, **Then** the plan contains only the relevant tasks (it does not schedule unrelated agents).
3. **Given** an objective whose required capability maps to a disabled or unavailable agent, **When** the CEO plans, **Then** the CEO applies a defined policy (approved fallback, wait, or escalate) and records the decision; it does not silently drop the task.
4. **Given** a plan is created, **When** any user with the appropriate role opens the console, **Then** the plan's objective, tasks, assignments, and dependencies are visible and match the persisted record exactly.

---

### User Story 2 - Independent work runs in parallel; dependent work waits (Priority: P1)

Once the CEO has a plan, tasks with no unmet dependencies start concurrently. A task whose inputs are not yet available enters a waiting state and starts only when every required input exists. Each task moves through an explicit lifecycle; the organisation records start time, finish time, duration, whether it ran concurrently with siblings, and how long it spent waiting on dependencies. Task status, agent status, organization-run status, and approval status are tracked as separate concepts.

**Why this priority**: This is the core behavioural change from "fixed sequential chain" to "organisation." It delivers real speed-up and correctness (dependent agents never run on missing inputs) and is the audit's central architectural gap.

**Independent Test**: Run an objective whose plan has four independent tasks and two dependent tasks; confirm from recorded timings that the four independent tasks overlap in wall-clock time; confirm each dependent task's recorded start is at or after its last dependency's recorded completion; confirm a dependent task never produces output when a required input is absent; confirm a mandatory concurrency test (four independent research tasks overlap, then sentiment waits for news, risk waits for portfolio, strategy waits for its full input set) passes.

**Acceptance Scenarios**:

1. **Given** a plan with independent market, news, portfolio, and data tasks, **When** execution begins, **Then** all four enter running state without any waiting on another, and their recorded run windows overlap.
2. **Given** a sentiment task that depends on a news task, **When** the news task has not completed, **Then** the sentiment task is in a waiting-for-dependency state showing what it is waiting for and who owns it; **When** the news task completes, **Then** a dependency-satisfied event fires and the sentiment task becomes ready and then runs.
3. **Given** a strategy task depending on market, data, sentiment, and risk outputs, **When** any one of those is missing, **Then** the strategy task remains blocked/waiting and does not execute.
4. **Given** any task, **When** it completes, fails, retries, is escalated, or is cancelled, **Then** its own status reflects that, distinctly from the assigned agent's status and the overall organization-run status.
5. **Given** an upstream task permanently fails after its retry budget, **When** a downstream dependent task's dependency can never be satisfied, **Then** the downstream task is marked blocked with a clear reason and does not falsely complete.

---

### User Story 3 - Real human approval before a strategy enters Paper Trading (Priority: P1)

When the organisation produces a deployment recommendation for a new strategy, the strategy enters a **pending-approval** state and is **not** placed into Paper Trading. A human with the appropriate role reviews the recommendation (plain-language logic, generated code, backtest and optimisation results, risk and compliance findings, readiness-gate status) and explicitly approves or rejects it, with a recorded reason. Only an approval transitions the strategy into Paper Trading. Paper→Live remains a separate, explicit, role-gated human action, unchanged.

**Why this priority**: The audit finds the current approval is post-hoc — the strategy is already in Paper Trading before any human acts, and "approve" changes nothing. This is a governance/state-integrity defect and a direct violation of the documented Deployment Agent contract. It is small, bounded, and high-value.

**Independent Test**: Run a research objective to a deployment recommendation; confirm the strategy's state is "pending approval", not "paper trading"; confirm no scheduled job or agent transitions it automatically; approve it as an authorised role and confirm it moves to Paper Trading and the approval is audited with actor, timestamp, and reason; in a separate run, reject and confirm the strategy is marked rejected/deprecated and never entered Paper Trading; confirm a non-authorised role cannot approve.

**Acceptance Scenarios**:

1. **Given** the organisation completes a run with a deploy recommendation, **When** the run finishes, **Then** the strategy status is "pending paper approval" and an approval-requested event is emitted.
2. **Given** a pending strategy, **When** an authorised human approves it, **Then** the strategy transitions to Paper Trading, an approval-approved event and audit entry (actor, time, reason) are recorded, and the console reflects the new state within the live-update budget.
3. **Given** a pending strategy, **When** an authorised human rejects it with a reason, **Then** the strategy is marked rejected, it never enters Paper Trading, and the reason is captured in the audit trail.
4. **Given** a pending strategy, **When** an un-authorised user attempts to approve it, **Then** the action is denied and the denial is audited.
5. **Given** any strategy in Paper Trading, **When** a human requests promotion to Live, **Then** the existing separate role-gated Live approval path is required and is unchanged by this feature.

---

### User Story 4 - News, sentiment, and portfolio intelligence actually inform research (Priority: P1)

News output is available to downstream work; sentiment analysis consumes/references the relevant news; portfolio state participates in the CEO's decisions and is available to risk assessment; and the strategy-generation step receives the assembled organisational context (market + news + sentiment + portfolio + risk, as applicable to the objective). No specialist agent's output is produced and then discarded.

**Why this priority**: The audit finds these agents run in isolation and their outputs are consumed by nothing — the product is "one pipeline plus cron jobs." Wiring them in is what makes the organisation coherent and is a prerequisite for the CEO making informed decisions.

**Independent Test**: Run an objective that warrants news/sentiment context; confirm from recorded task inputs that the strategy-generation task received a sentiment/news context artefact traceable to that run's own news and sentiment tasks; disable the news task and confirm the sentiment task and downstream context degrade honestly (clearly marked reduced coverage) rather than silently proceeding as if full data were present; confirm portfolio output appears among the inputs to at least one CEO decision and to the risk assessment when the objective involves portfolio impact.

**Acceptance Scenarios**:

1. **Given** a research objective with priority sectors, **When** the plan runs, **Then** the news task produces a digest, the sentiment task consumes that digest, and the strategy-generation task's recorded inputs include a sentiment/news context artefact from this run.
2. **Given** a news source is unavailable, **When** the news task runs, **Then** it reports reduced coverage, the sentiment task and any assembled context carry that reduced-confidence marker, and nothing presents partial data as complete.
3. **Given** an objective that affects portfolio exposure, **When** the CEO makes a decision, **Then** the decision's recorded supporting inputs include the portfolio state, and the risk assessment's inputs include portfolio data.
4. **Given** any completed run, **When** its result artefacts are inspected, **Then** every specialist artefact produced (news digest, sentiment report, portfolio report, etc.) is either consumed by a downstream task or explicitly recorded as informational-only — none is silently orphaned.

---

### User Story 5 - Organization Command Center console (Priority: P2)

The Agent Console is redesigned as a live command centre for the organisation. It shows organisation health, the current objective, the active plan, which agents are running, waiting, blocked, or escalated, pending approvals, recent decisions, recent failures, and the freshness of required data. A live activity stream shows real backend events as they happen. The user can open any agent — graph or non-graph — into a uniform detail view (overview, current task, inputs, outputs, tools used, skills available, model/provider in use and whether it is default or overridden, activity timeline, upstream dependencies, downstream consumers, previous runs, recent errors, result artefacts, audit references). The user can inspect a completed run's operational history (plan, task creation, parallel execution, dependency resolution, hand-offs, results, retries, decisions, approval, outcome). All displayed status is derived from real runtime state; no hard-coded status text, no "approved" unless a real approval occurred, no "running" unless the backend says so. The console updates live without manual refresh.

**Why this priority**: The audit finds the console mostly shows the orchestrator, has no view of the non-graph agents, presents an inaccurate approval picture, and carries stale hard-coded copy. It is the product surface where "the organisation feels alive." It depends on US1–US4 producing real state to display.

**Independent Test**: With an organisation run in progress, confirm the console shows the plan, concurrently-running agents as concurrent, a waiting agent with its stated reason and expected next event, and a dependency becoming satisfied — all matching backend records; select three different agents (including one non-graph agent) and confirm each renders the same uniform detail framework populated with that agent's real data; open a completed run and confirm every operational step is reconstructable; confirm no screen contains a status string that is not backed by a live value; disconnect and reconnect the live channel and confirm the console re-syncs without a full page reload.

**Acceptance Scenarios**:

1. **Given** an active run, **When** the user opens the console home, **Then** it summarises CEO status, organisation health, current objective, running/waiting/blocked agent counts, pending approvals, recent decisions, recent failures, and data freshness, all from live state.
2. **Given** an active run, **When** two independent agents are running, **Then** the organisational graph shows both as active simultaneously and animates a dependency edge activating when that dependency is satisfied — reflecting real state, never simulated.
3. **Given** any agent, **When** the user selects it, **Then** the uniform agent detail view opens showing at minimum its current task, inputs, outputs, tools/skills, model/provider (with default-vs-override indicator), activity timeline, dependencies, consumers, previous runs, errors, artefacts, and audit references.
4. **Given** an agent is waiting, **When** the user views it, **Then** the console states what it is waiting for, why, and the expected next event.
5. **Given** an agent has failed, **When** the user views it, **Then** the console shows the agent, task, reason, impact, retry status, effect on dependents, the CEO's response, and a recommended action — not merely "Failed".
6. **Given** a CEO decision, **When** the user views it, **Then** it is shown as an operational summary (decision, reason, supporting inputs, next step) without exposing private model reasoning.
7. **Given** a completed run, **When** the user opens run replay, **Then** plan, task timeline, dependencies, hand-offs, results, retries, decisions, and approval/outcome are all reconstructable from recorded events.

---

### User Story 6 - Per-agent Settings: prompt versions and provider/model (Priority: P2)

A dedicated Agent Settings area (separate from generic global settings) lets an authorised user select any individual agent and manage: its active system prompt and full version history (author, dates, change summary, diff view, activate, roll back); and its AI provider and model. Provider/model defaults to **AUTO** — meaning "use the existing configured routing policy" — and the current behaviour is unchanged unless the user explicitly sets a custom provider and a valid model. The UI only offers providers and models that are actually configured and valid; it invents nothing. Every prompt or provider/model change is recorded with who, what changed, old value, new value, timestamp, reason, and an audit reference. A test panel lets the user trial a prompt/model configuration (showing provider, model, latency, whether structured output validated, token/cost if available, and errors) before activating it. Prompt changes are role-gated, versioned, validated, diffable, auditable, and reversible — an accidental production overwrite is prevented.

**Why this priority**: The brief makes this a major new requirement, and the audit notes prompt editing currently requires editing files and redeploying, and that there is no per-agent model control. It depends on the agent registry (US1) existing and on a real notion of "which model an agent used" (US5 detail view).

**Independent Test**: For one agent, view its active prompt and version history; create a new version, review the diff, and confirm it is not active until explicitly activated; set a custom provider and a valid model, run the test panel, and confirm it reports the real provider/model/latency/validation; activate the configuration, confirm an audit entry with before/after values, run the agent, and confirm the agent actually used the configured provider/model; for a second agent left on AUTO, run it and confirm its provider/model selection is byte-for-byte the current routing behaviour (no silent change); attempt a prompt change as an unauthorised role and confirm it is denied and audited.

**Acceptance Scenarios**:

1. **Given** the Agent Settings area, **When** an authorised user selects an agent, **Then** they see its active prompt, version history with metadata, and its provider/model configuration (defaulting to AUTO).
2. **Given** an agent on AUTO, **When** it runs, **Then** its provider/model is selected exactly by the existing routing policy — this feature introduces no change to default behaviour.
3. **Given** a user sets a custom provider, **When** they choose a model, **Then** only models that are actually configured for that provider and valid for the agent are offered; an invalid combination cannot be activated.
4. **Given** a new prompt version or a provider/model change, **When** it is saved, **Then** it is inactive until explicitly activated, and activation records who/what/old/new/when/why with an audit reference.
5. **Given** an active configuration, **When** the user rolls back to a previous prompt version, **Then** the rollback is itself an audited, versioned change and takes effect on the agent's next run without a redeploy.
6. **Given** the console agent detail view, **When** an agent has a custom override, **Then** it clearly shows "custom model override active"; otherwise it shows "using default routing".
7. **Given** the model override precedence (global default → agent default → permitted per-task override → emergency fallback routing), **When** multiple levels are set, **Then** the effective selection follows that documented order and the console shows which level applied.

---

### User Story 7 - Data-freshness awareness across the organisation (Priority: P2)

Required datasets (e.g. end-of-day market data) have a defined ingestion cadence, a readiness/freshness definition, integrity (checksum) validation, and retry/failure handling. When a dataset needed for a task is missing or stale, the CEO knows before planning or dispatching work that depends on it, and either defers that work with a clear reason or proceeds with the rest of the plan while surfacing the gap. The console shows current data freshness. Stale or failed ingestion raises an alert. The system never fabricates or interpolates missing market data to pass a freshness check.

**Why this priority**: The audit finds the running environment's market data is ~2 years stale, so the freshness gate would reject any real backtest — the autonomous loop cannot currently complete for this reason independent of anything else. Making freshness a first-class, visible organisational fact (and fixing the ingestion cadence) unblocks real runs and prevents silent wrong results.

**Independent Test**: With a required dataset marked stale, submit an objective that needs it and confirm the CEO defers the dependent tasks with an explicit "data stale" reason while still running independent tasks; confirm the console data-freshness panel shows the stale state and an alert is raised; refresh the dataset (with checksum validation) and confirm the previously-deferred tasks become eligible; confirm no code path substitutes synthetic data to satisfy the check; confirm a corrupt/failed ingestion is detected and does not mark the dataset fresh.

**Acceptance Scenarios**:

1. **Given** a dataset past its freshness threshold, **When** an objective requiring it is submitted, **Then** the CEO records that the dataset is stale, defers dependent tasks with that reason, and proceeds with independent tasks.
2. **Given** the console, **When** the user views organisation health, **Then** the freshness of each required dataset is shown with its last successful update and status.
3. **Given** an ingestion run, **When** it fails or produces data that fails checksum validation, **Then** the dataset is not marked fresh, an alert is raised, and retry/backoff behaviour follows the defined policy.
4. **Given** stale data, **When** any task attempts to proceed, **Then** the system does not fabricate or interpolate values to pass the check.

---

### User Story 8 - Agent-first ad-hoc analysis and omni-channel objectives (Priority: P2)

Meaningful "do something" requests are handled by agents, not by returning static dashboard data dressed up as analysis. Requests such as "analyze my portfolio", "which positions have the highest risk", "why did my strategy draw down", "why did this strategy fail", and "should we rerun this strategy" invoke the appropriate agents and tools and return a result traceable to a real agent execution. Objectives submitted via web chat or connected messaging channels (Telegram, Discord, Slack) reach CEO orchestration where appropriate: a request like "run today's research" creates a real organisational plan and returns the CEO's synthesis — it does not produce a generic model answer with no organisational task behind it. Dashboards continue to visualise results, positions, performance, history, and analytics; they do not replace the organisation.

**Why this priority**: The brief's "agent-first product rule" and the audit's "incomplete omni-channel research trigger" and "no conversational analytical agents" findings. It broadens the transformation to the surfaces users actually touch. It depends on the orchestration core (US1–US2) and the agent registry.

**Independent Test**: Submit "analyze my portfolio and identify the highest-risk positions" via chat and confirm it creates a task/run assigned to an appropriate agent, uses real portfolio data, and returns a result linked to that execution and to an audit entry; submit "run today's research" via a connected channel and confirm a real Organizational Plan is created and the reply is the CEO synthesis of that run; confirm that asking a purely informational question ("what is my current P&L") is answered without needlessly creating an organisational run.

**Acceptance Scenarios**:

1. **Given** the user asks an analytical question that requires work, **When** it is submitted, **Then** an agent/task is created, real data and tools are used, and the answer is traceable to that execution and audited.
2. **Given** the user submits an objective via a connected messaging channel, **When** it warrants orchestration, **Then** a real plan is created, agents execute, and the channel reply is the CEO's synthesis of the actual run — not a standalone model response.
3. **Given** a request that is purely a data lookup, **When** it is submitted, **Then** it is answered directly without creating an unnecessary organisational run.
4. **Given** any agent-driven analysis result, **When** the user inspects it, **Then** they can see which agent produced it, from which inputs, using which tools, at which time.

---

### User Story 9 - Enforced agent enable/disable across all agents (Priority: P3)

Every agent's enable/disable state actually affects execution. A disabled agent cannot be assigned work by the CEO; queued or in-flight tasks for it follow a defined policy (fallback, reassignment, wait, or escalation); an enable/disable change emits an event and an audit entry; and the console shows the real, current state. This closes the audit gap where several agents' control state is stored but never checked.

**Why this priority**: Important for operational safety and truthfulness, but lower urgency than the orchestration core and console; it hardens behaviour rather than adding a primary capability.

**Independent Test**: Disable an agent that a plan would require; submit that objective and confirm the CEO recognises the missing capability and applies the configured policy (approved fallback, wait, reassign, or escalate) with a recorded decision — it does not dispatch the disabled agent; re-enable it and confirm subsequent plans use it again; confirm the audit trail contains both the disable and the enable with actor and time; confirm the audit agent cannot be disabled.

**Acceptance Scenarios**:

1. **Given** an agent is disabled, **When** the CEO plans an objective needing that capability, **Then** the CEO cannot assign work to it and instead applies the configured unavailable-capability policy, recording the decision.
2. **Given** an agent is disabled while it has queued tasks, **When** those tasks are evaluated, **Then** each follows the defined policy and none is silently lost.
3. **Given** an enable or disable action, **When** it is applied, **Then** an event and an audit entry (actor, time, reason) are written and the console reflects the change.
4. **Given** the audit agent, **When** any user attempts to disable it, **Then** the action is refused (immutable audit trail requirement).

---

### Edge Cases

- **Disabled/unavailable agent needed by a plan** — CEO applies a defined policy (approved fallback, wait, retry, reassign, escalate) and records the decision; the task is never silently dropped.
- **AI provider outage or a provider returning errors** — routing falls back per the existing policy; the console shows the provider actually used; a fallback is recorded where applicable; the agent remains transparent about which model answered.
- **Two agents disagree** (e.g. market analyst bullish, sentiment bearish, risk high) — the CEO detects the disagreement, inspects the evidence, optionally requests further review, makes an organisation-level decision, records the decision and its rationale, and escalates to a human if required.
- **A dependency can never be satisfied** because an upstream task exhausted its retries — the dependent task is marked blocked with a clear reason; it does not falsely complete; the CEO is notified.
- **Required dataset is stale or ingestion failed** — the CEO defers dependent work with an explicit reason, runs independent work, surfaces the gap in the console, and raises an alert; no synthetic data is substituted.
- **A human approval is never given** — the strategy stays pending indefinitely and never enters Paper Trading; the pending item remains visible in the approvals queue; no timeout auto-approves it.
- **The kill switch trips mid-run** — the deterministic risk engine remains supreme; the organisation halts strategy-deployment progress consistent with the existing kill-switch behaviour; the CEO cannot override it.
- **Concurrent organisational runs** — each run has its own plan, tasks, timeline, and state; runs do not corrupt one another's records; the console can show and switch between them.
- **An agent fails repeatedly past its retry budget** — the task is marked failed, the CEO receives a failure event, and downstream dependents do not falsely complete; the console shows the true state; the failure is audited.
- **A per-agent custom model override is invalid** at run time (model since removed/unconfigured) — the agent falls back per the documented precedence, the console shows the effective selection and that a fallback occurred, and the invalid override is flagged in settings.
- **Live channel disconnect** during an active run — the console reconnects and re-syncs from backend state without a full reload and without losing the selected run/agent context.
- **An objective the organisation genuinely cannot serve** (no capable agent, no data) — the CEO returns an explicit "cannot plan / cannot proceed" outcome with the reason; it does not fabricate a plan or a result.

---

## Requirements *(mandatory)*

### Functional Requirements — Orchestration & Planning

- **FR-001**: The system MUST accept a plain-language objective from an authorised owner, a schedule, or a connected messaging channel, and route it to the CEO agent for planning.
- **FR-002**: The CEO MUST produce, per objective, an Organizational Plan containing: the objective, a plan identifier, a set of tasks, an assigned agent per task, per-task priority, declared dependencies, expected outputs, applicable constraints, a deadline where relevant, and any safety and approval requirements.
- **FR-003**: Plans MUST be generated dynamically from the objective; the system MUST NOT execute a single fixed sequential chain for every objective.
- **FR-004**: The CEO MUST NOT personally perform specialist work that a specialist agent exists to do; its role is classify, plan, delegate, monitor, consume results, resolve conflicts, decide next steps, synthesise, and communicate.
- **FR-005**: Before assigning a task, the system MUST verify the target agent is enabled, healthy, available, has its required skills/tools/permissions, has the required data, and has an available model/provider; if not, the CEO MUST apply a defined policy (approved fallback, wait, retry, reassign, or escalate) and record the decision.
- **FR-006**: The CEO MUST select an agent for a task by required capability via the agent registry, not by hard-coded agent-identifier routing wherever a capability lookup is feasible.
- **FR-007**: The system MUST record a dependency graph per plan and MUST reject or repair a plan whose dependency graph contains a cycle or references a non-existent agent.
- **FR-008**: An objective the organisation cannot serve MUST produce an explicit, recorded "cannot plan" outcome; the system MUST NOT emit an empty or fabricated plan.
- **FR-009**: The system MUST support a small, fixed, configurable number of concurrently active organization runs (default 3). When that limit is reached, a newly submitted objective MUST be queued (with a recorded, visible queued state) and started automatically when a slot frees; it MUST NOT be dropped or silently merged into another run. Each active run MUST have its own plan, task set, timeline, and state, isolated from other runs' records.

### Functional Requirements — Task Model, Lifecycle & Dependencies

- **FR-010**: The system MUST model a first-class Task with at least: identifier, parent task, owning organization-run, tenant, objective/description, assigned agent, creator, priority, dependencies, dependency policy, required inputs, received inputs, expected output, result reference, status, retry count, maximum retries, timeout, deadline, created/started/completed timestamps, failure reason, correlation identifier, and audit reference.
- **FR-011**: The system MUST support the task lifecycle states: created, planned, queued, ready, running, waiting-for-dependency, waiting-for-agent, blocked, awaiting-approval, completed, failed, retrying, escalated, cancelled, superseded.
- **FR-012**: The system MUST track task status, agent status, organization-run status, and approval status as separate, non-conflated concepts.
- **FR-013**: Tasks with no unmet dependencies MUST be eligible to run concurrently; the system MUST run independent tasks concurrently where it is technically safe to do so.
- **FR-014**: A task with an unmet dependency MUST NOT execute; it MUST enter a waiting state that records what it is waiting for and which task/agent owns that dependency.
- **FR-015**: When a task's last outstanding dependency is satisfied, the system MUST emit a dependency-satisfied event and make the task ready.
- **FR-016**: For each task the system MUST record start time, finish time, duration, whether it ran concurrently with sibling tasks, and total dependency wait time.
- **FR-017**: When an upstream task permanently fails, each downstream task whose dependency can no longer be satisfied MUST be marked blocked with a clear reason and MUST NOT be reported as completed.
- **FR-018**: The system MUST apply per-task retry policy (bounded by maximum retries) and MUST escalate to the CEO — and, where configured, notify a human — on repeated failure.
- **FR-019**: Organization-run and task state MUST be durably persisted such that, after an application restart while a run is in progress, the run resumes automatically from its last completed task/checkpoint; completed tasks and their result artefacts MUST NOT be re-executed. A task that was mid-execution at restart MUST be re-attempted (subject to its retry budget) or, if not safely re-runnable, marked failed with a reason — never reported as completed.

### Functional Requirements — Collaboration, Review & Conflict

- **FR-020**: The system MUST support structured agent interactions: CEO→agent delegation, agent→agent hand-off, agent→agent review, agent→agent feedback, agent→CEO escalation, CEO→agent reassignment, and result-artefact→downstream-agent consumption — carried as structured records, not solely as free-text prompt content.
- **FR-021**: The system MUST support specialist peer review where the objective or risk justifies it (for example: strategy reviewed by risk; generated code reviewed by the validator; backtest reviewed by the evaluator; risk reviewed by compliance) and MUST NOT force peer review on every trivial operation.
- **FR-022**: When specialist outputs conflict, the CEO MUST detect the disagreement, inspect the supporting evidence, optionally request further analysis or review, make an organisation-level decision, record the decision and its rationale and supporting inputs, and escalate to a human where required.
- **FR-023**: Every CEO decision MUST be recorded as an operational summary (decision, reason, supporting agents/inputs, next step) suitable for display and audit, without exposing private model chain-of-thought.

### Functional Requirements — Structured Results & Memory

- **FR-030**: Every agent result MUST be a typed artefact carrying provenance: producing agent, task, organization-run, version, timestamp, inputs used, tools used, and an audit reference.
- **FR-031**: Every artefact a run produces MUST be either consumed by a downstream task or explicitly recorded as informational-only; no artefact may be silently orphaned.
- **FR-032**: The CEO MUST have access to organisational memory covering at least: previous plans, successful/rejected/failed strategies, failed validations, prior market conditions, prior risk decisions, prior CEO decisions, and recorded lessons — served from the existing vector-memory infrastructure, not a new memory platform.
- **FR-033**: On a failed or rejected strategy, the run MUST record the outcome to organisational memory so future planning and generation can avoid repeating it.

### Functional Requirements — Context Integration (audit BUG-C)

- **FR-040**: News output MUST be made available to downstream tasks within the same run.
- **FR-041**: The sentiment step MUST consume or reference the relevant news output from the same run.
- **FR-042**: The strategy-generation step MUST receive an assembled organisational context artefact appropriate to the objective (market, news, sentiment, portfolio, risk as applicable).
- **FR-043**: Portfolio state MUST be among the recorded inputs to at least one CEO decision when the objective affects portfolio exposure, and MUST be available to the risk assessment where required.
- **FR-044**: When an input source is unavailable, the assembled context MUST carry an explicit reduced-coverage/reduced-confidence marker; the system MUST NOT present partial context as complete.

### Functional Requirements — Safety & Human Governance (audit BUG-B)

- **FR-050**: The deterministic risk engine, kill switch, compliance checks, RBAC, and broker controls MUST retain final authority; the organisational/CEO layer MUST NOT be able to override, bypass, reorder around, or disable them.
- **FR-051**: Strategy safety ordering (validation → compliance → backtest → evaluation → risk) and signal safety ordering (deterministic risk → compliance → governed execution) MUST be preserved regardless of organisational parallelism.
- **FR-052**: A new strategy MUST enter a pending-approval state on a deployment recommendation and MUST NOT be placed into Paper Trading until an authorised human explicitly approves it.
- **FR-053**: The pending→Paper-Trading approval and its rejection MUST be restricted to the `SystemAdministrator` and `PortfolioManager` roles (the same authority as the existing Paper→Live promote gate); every other role MUST be denied and the denial audited. Approval and rejection MUST each require a recorded reason on rejection and MUST be captured in the audit trail with actor and timestamp.
- **FR-054**: A rejected strategy MUST be marked rejected/deprecated and MUST never enter Paper Trading.
- **FR-055**: Promotion from Paper Trading to Live MUST remain a separate, explicit, role-gated human action, unchanged by this feature.
- **FR-056**: No agent, scheduled job, or code path may place a live order or move real funds automatically; any future need to do so MUST be flagged for explicit human review rather than implemented.
- **FR-057**: A pending approval MUST NOT be auto-approved by any timeout or default; it remains pending until a human acts.

### Functional Requirements — Data Freshness (audit BUG-A)

- **FR-060**: Each required dataset MUST have a defined ingestion cadence, a freshness/readiness definition, integrity (checksum) validation on ingest, and a retry/backoff-and-failure policy.
- **FR-061**: The CEO MUST be able to determine, before dispatching a task, whether that task's required datasets are fresh, stale, or unavailable.
- **FR-062**: When a required dataset is stale or unavailable, the CEO MUST defer the dependent tasks with an explicit reason while still running independent tasks, and the gap MUST be surfaced in the console and raised as an alert.
- **FR-063**: The system MUST NOT fabricate, interpolate, or synthesise missing market data to satisfy a freshness check.
- **FR-064**: A failed ingestion or one that fails checksum validation MUST NOT mark the dataset fresh.

### Functional Requirements — Missing Skills & Data Honesty (audit BUG-D)

- **FR-070**: Skills for which a real data source is practically available (for example global-indices retrieval and stored-sentiment lookup) MUST be implemented against a real source rather than left unimplemented.
- **FR-071**: For a data source that is genuinely unavailable (for example a live regulatory position-limit feed), the system MUST NOT fabricate data; it MUST expose the source limitation, the actual data coverage, the fallback behaviour, and the governance implication of the gap.

### Functional Requirements — Organization Command Center Console (audit BUG-C, BUG-G)

- **FR-080**: The console home MUST summarise CEO status, organisation health, current objective, active run, counts of running/waiting/blocked agents, pending approvals, recent decisions, recent failures, and required-data freshness — all from live backend state.
- **FR-081**: The console MUST visualise the actual runtime organisational task graph, showing independent agents as concurrent and animating dependency-edge activation only when the backend reports the dependency satisfied; it MUST NEVER display simulated or fabricated graph activity.
- **FR-082**: The console MUST let the user open any agent — pipeline or non-pipeline — into a uniform detail view containing at least: overview (name, role, department, status, health, enabled state), current task (objective, assigned by, priority, dependencies, progress, start time), inputs, outputs, tools used, skills available, model/provider in use with a default-vs-override indicator (or "no model — deterministic" for a deterministic agent), activity timeline, upstream dependencies, downstream consumers, previous runs, recent errors, result artefacts, and audit references.
- **FR-083**: A waiting agent's view MUST state what it is waiting for, the reason, and the expected next event.
- **FR-084**: A failed agent's view MUST show agent, task, reason, impact, retry status, effect on dependents, the CEO's response, and a recommended action — not merely "Failed".
- **FR-085**: The console MUST present an operational CEO activity stream (e.g. "waiting for risk output", "detected disagreement between market and sentiment", "deployment requires human approval") without exposing private model reasoning.
- **FR-086**: The console MUST provide a department/organisation view grouping agents (Executive, Market Intelligence, Research, Quant, Risk & Governance, Portfolio, Operations) that is navigable to a department or an agent.
- **FR-087**: The console MUST provide run replay for a completed run: plan, task creation, parallel execution, dependency resolution, hand-offs, results, failures, retries, decisions, approval, and outcome — reconstructed from recorded events, without exposing private model reasoning.
- **FR-088**: The console MUST update live for task state, agent state, dependency satisfaction, task completion, result creation, approval request, approval decision, failure, and escalation, using the existing event/streaming infrastructure, without requiring a manual page refresh.
- **FR-089**: The console MUST NOT display any hard-coded status text; every status string MUST be derived from a live value. It MUST NOT show "approved" unless a real approval occurred, or "running" unless the backend reports running.
- **FR-090**: The user MUST be able to switch between agents and back to the CEO without losing the selected organisation run, selected task, time range, or context.
- **FR-091**: For a selected agent the console MUST show metrics: total runs, success rate, failure rate, average duration, retries, escalations, current queue depth, last successful and last failed execution, tool usage, model usage, and token/cost where available.

### Functional Requirements — Agent Settings & Provider/Model (brief §44–§53)

- **FR-100**: The system MUST provide a dedicated Agent Settings area, distinct from generic global settings, in which an authorised user selects an individual agent.
- **FR-101**: For a selected agent the settings area MUST show the active system prompt and the full version history with author, created and modified dates, change summary, and a diff view; and MUST support activating a version and rolling back.
- **FR-102**: Prompt changes MUST take effect on the agent's next run without a code change or redeploy, consistent with the existing dynamic prompt-management capability.
- **FR-103**: Activating or rolling back a prompt version, and setting or clearing a custom provider/model, MUST be restricted to the `SystemAdministrator` role; every other role MUST be denied and the denial audited. These changes MUST be versioned, validated, diffable, auditable, and reversible; the system MUST prevent an accidental overwrite of the active production prompt (a new version is inactive until explicitly activated). Viewing an agent's configuration and version history MAY be available to any role permitted to view the console.
- **FR-104**: For a selected **LLM-backed** agent the settings area MUST offer an AI provider and model selection that defaults to AUTO, meaning "use the existing configured routing policy"; with AUTO selected, the agent's provider/model selection MUST be identical to current behaviour. For a **deterministic** agent (one that makes no model call — e.g. the validator, backtesting, compliance checker, data ingestion, scheduler, audit), the settings area MUST show "no model — deterministic" and MUST NOT present a provider/model picker.
- **FR-105**: The provider and model pickers (shown only for LLM-backed agents per FR-104) MUST offer only providers and models that are actually configured and valid; the system MUST NOT display invented provider names or models, and MUST reject activation of an invalid provider/model combination.
- **FR-106**: The effective model selection MUST follow a documented precedence: global default → agent default → permitted per-task override → emergency/fallback routing; the console MUST indicate which level applied ("using default routing" vs "custom model override active").
- **FR-107**: Every prompt change and every provider/model change MUST record who changed it, what changed, the old value, the new value, timestamp, reason, the agent, the prompt version, the provider, the model, and an audit reference.
- **FR-108**: The settings area MUST provide a test panel that trials a prompt/model configuration and reports provider, model, latency, whether structured output validated, tool compatibility, token/cost where available, and any errors; activation MUST be allowed only for a valid configuration.
- **FR-109**: The settings/detail views MUST show, per agent, available skills, available tools, enabled skills, disabled skills, and permissions; where supported, the `SystemAdministrator` role MAY enable or disable a skill for an agent (same authority as prompt/model changes), and the change MUST be audited.
- **FR-110**: The settings area MUST show provider health per provider/model: availability, latency, last failure, and fallback state — derived from real signals, never fabricated.

### Functional Requirements — Agent Enable/Disable Enforcement (audit "incomplete agent-control enforcement")

- **FR-120**: Every agent's enable/disable state MUST actually affect execution: a disabled agent cannot be assigned work, and its queued or in-flight tasks MUST follow a defined policy (fallback, reassignment, wait, or escalation) with none silently lost.
- **FR-121**: An enable or disable action MUST emit an event and write an audit entry (actor, timestamp, reason), and the console MUST reflect the real state.
- **FR-122**: The audit agent MUST NOT be disable-able.

### Functional Requirements — Omni-Channel & Ad-Hoc Analysis (audit "incomplete omni-channel research trigger")

- **FR-130**: A "do something meaningful" request (analyse portfolio, identify highest-risk positions, explain a drawdown, explain a strategy failure, decide whether to rerun) MUST be executed by the appropriate agent(s) and tools, and the answer MUST be traceable to a real agent execution and an audit entry.
- **FR-131**: The system MUST NOT return static dashboard data presented as if an agent performed the analysis.
- **FR-132**: An objective submitted via a connected messaging channel that warrants orchestration MUST create a real Organizational Plan, execute agents, and reply with the CEO's synthesis of that run — not a standalone model answer with no organisational task behind it.
- **FR-133**: A request that is purely a data lookup MUST be answerable without creating an unnecessary organisational run.
- **FR-134**: Dashboards MUST continue to visualise results, risk, positions, performance, history, and analytics, and MUST NOT be the mechanism by which meaningful work is performed.

### Functional Requirements — Events & Observability (audit "observability limitations")

- **FR-140**: The system MUST emit organisational events covering at least: plan created/updated/completed; task created/queued/started/waiting/ready/completed/failed/retrying/escalated/cancelled; agent started/completed/failed/disabled; dependency created/satisfied/failed; result created/available; review requested/completed; approval requested/approved/rejected; and CEO decision created.
- **FR-141**: Events MUST be produced from real state transitions and MUST be the source of the console's live updates and run replay.
- **FR-142**: Every meaningful organisational action (plan, task transition, decision, review, approval, configuration change, agent enable/disable, escalation, failure) MUST be captured in the immutable audit trail with sufficient context to reconstruct it later.

### Functional Requirements — Non-Regression & Reuse (brief §22, §88; audit "real LangGraph foundation")

- **FR-150**: The transformation MUST reuse and extend the existing LangGraph orchestration, LLM router, SkillRegistry, sandbox, deterministic risk engine, compliance checks, vector memory, cache/pub-sub, relational store, scheduler, audit architecture, and existing frontend foundations; it MUST NOT replace any of them without a concrete requirement that proves replacement necessary.
- **FR-151**: The existing research pipeline's working components (backtesting, walk-forward/Monte-Carlo/Optuna optimisation, hardcoded risk, compliance, sandbox, RAG) MUST continue to function; they are refactored into coordinated organisational tasks, not discarded.
- **FR-152**: Existing user-facing dashboards, existing authenticated routes, and existing test suites MUST continue to pass; any behavioural change MUST be intentional, specified, and covered by a test.
- **FR-153**: Default runtime behaviour for any agent left on AUTO provider/model MUST be byte-for-byte the current routing behaviour after this feature ships.

### Functional Requirements — Audit-Finding Coverage

- **FR-160**: The delivery MUST address each of the following audit findings, each traceable to a user story, functional requirement(s), test, and acceptance criterion (see the Audit Traceability table): BUG-A (stale data blocks the autonomous run), BUG-B (approval is post-hoc, not a gate), BUG-C (news/sentiment/portfolio outputs unconsumed), BUG-D (stubbed skills), BUG-E (CI not green on a clean checkout), BUG-F (live pipeline does not persist order records), BUG-G (stale console caption/hard-coded status), BUG-H (stale docstrings), BUG-I (agent lifecycle states in docs not modelled in status).
- **FR-161**: BUG-E: the continuous-integration pipeline MUST be green on a clean checkout (test data seeding included; environment-only failures such as expiring third-party broker tokens quarantined from the default gate).
- **FR-162**: BUG-F: order records created by the live execution path MUST be persisted and reconcilable, and MUST be published to the live order-status stream, consistent with the manually-triggered order path.
- **FR-163**: BUG-H / BUG-I: developer-facing documentation and any lifecycle terminology MUST match the implemented state model; stale claims MUST be corrected.

### Functional Requirements — Accessibility, Responsiveness & Performance (brief §57–§59)

- **FR-170**: The console and settings surfaces MUST support keyboard navigation, visible focus states, sufficient contrast, semantic status labels usable by assistive technology, and a reduced-motion mode.
- **FR-171**: The command centre MAY prioritise desktop layouts, but monitoring and approvals MUST remain usable on tablet and mobile.
- **FR-172**: Live updates MUST be event-driven (no polling where events are available), MUST avoid duplicate streaming subscriptions, and MUST remain responsive with large agent/task lists (virtualised where necessary) and large runtime graphs.

### Key Entities *(conceptual — implementation defined in `/speckit-plan`)*

- **Organization Run**: one execution of the organisation against one objective. Has an objective, an owning plan, a status distinct from any task or approval status, a start/end time, participating agents, produced artefacts, decisions, and an audit reference. Multiple runs can be active concurrently and independently.
- **Organizational Plan**: the CEO's decomposition of an objective. Has a plan identifier, the objective, a task set, a dependency graph, priorities, constraints, deadline, and safety/approval requirements. Generated per objective.
- **Task**: a unit of delegated work assigned to one agent. Carries the full field set in FR-010, moves through the FR-011 lifecycle, and records timing including concurrency and dependency wait.
- **Task Dependency**: a directed relationship stating that a task requires a named input/artefact owned by another task; carries a dependency policy and a satisfied/unsatisfied/failed state.
- **Result Artefact**: a typed output of an agent (e.g. research directive, market context, news digest, sentiment report, portfolio risk report, allocation plan, strategy logic, options strategy proposal, generated code, validation report, compliance report, backtest metrics, optimisation report, risk report, evaluation report, deployment recommendation). Carries provenance (FR-030) and a consumed-or-informational marker (FR-031).
- **Organizational Decision**: a CEO-level decision (e.g. proceed, request review, escalate, choose fallback, resolve a conflict). Records the decision, reason, supporting inputs/agents, next step, timestamp, and audit reference; contains no private model reasoning.
- **Approval Request**: a pending human decision on a deployment recommendation. Has a subject strategy, a state (pending / approved / rejected), the reviewing actor and timestamp on resolution, and a mandatory reason on rejection. Never auto-resolves.
- **Agent (Capability Registry Entry)**: the organisation's directory record for an agent — identifier, name, department, role, description, capabilities, skills, tools, status, enabled flag, model/provider configuration, permissions, dependencies, concurrency limit, health, last execution, next scheduled execution. Used by the CEO to select agents by capability.
- **Agent Configuration**: per-agent settings — active prompt version reference; provider/model selection (AUTO or a specific configured pair) for LLM-backed agents only (deterministic agents carry no model selection); and per-agent skill enable/disable. All changes are `SystemAdministrator`-only, versioned, and audited.
- **Prompt Version**: an immutable version of an agent's system (or task) prompt — content, author, created/modified dates, change summary, and active/inactive state. New versions are inactive until explicitly activated; activation and rollback are audited.
- **Provider/Model Configuration**: the set of actually-configured providers and their valid models, plus per-provider health (availability, latency, last failure, fallback state). Drives the settings pickers and the console's default-vs-override indicator.
- **Organizational Event**: an immutable record of a real state transition (FR-140). The source of live console updates and run replay.
- **Dataset Freshness Record**: per required dataset — last successful update, checksum-validation result, freshness status (fresh / stale / unavailable / failed), ingestion cadence, and retry state.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For a research objective whose plan contains at least four independent tasks, the four independent tasks' recorded execution windows overlap, and total wall-clock time for the independent phase is at most the longest single independent task's duration plus a small scheduling overhead — not the sum of their durations.
- **SC-002**: In 100% of runs, a task with an unmet dependency has a recorded start time at or after the recorded completion of its last dependency; zero tasks execute with a required input absent.
- **SC-003**: In 100% of runs that reach a deployment recommendation, the subject strategy is in a pending-approval state and not in Paper Trading until a human approval is recorded; zero strategies enter Paper Trading without a recorded human approval.
- **SC-004**: For every completed run, 100% of specialist result artefacts produced are either consumed by a downstream task or explicitly marked informational-only; zero orphaned artefacts.
- **SC-005**: For an objective that warrants news/sentiment context, the strategy-generation task's recorded inputs include a context artefact traceable to that same run's news and sentiment tasks in 100% of such runs.
- **SC-006**: When a required dataset is stale or unavailable, 100% of dependent tasks are deferred with an explicit recorded reason and 0% proceed on fabricated or interpolated data; independent tasks in the same plan still run.
- **SC-007**: The console's displayed organisational state (which agents are running, waiting, blocked; pending approvals; decisions; data freshness) matches the backend records with no discrepancy on spot checks during an active run, and reflects a state change within the live-update budget (target: visible within 2 seconds of the backend event) without a manual refresh.
- **SC-008**: 100% of status strings shown in the console are backed by a live runtime value; a review finds zero hard-coded status text and zero "approved"/"running" labels without a corresponding real state.
- **SC-009**: A user can open any agent (pipeline or non-pipeline) into the uniform detail view and every listed section is populated from that agent's real data or explicitly marked "no data yet"; this holds for 100% of registered agents.
- **SC-010**: For an agent left on AUTO, its provider/model selection after this feature ships is identical to the pre-feature selection for the same inputs in 100% of sampled runs (no silent behaviour change).
- **SC-011**: A per-agent custom provider/model override, once activated, is the provider/model actually used by that agent's next run (verifiable from the run's recorded model usage) in 100% of cases, subject only to the documented fallback precedence when the override is unavailable.
- **SC-012**: 100% of prompt changes and provider/model changes produce an audit entry containing actor, before value, after value, timestamp, and reason.
- **SC-013**: When an agent required by a plan is disabled, the CEO applies a defined unavailable-capability policy and records the decision in 100% of such cases; the disabled agent is dispatched 0% of the time.
- **SC-014**: When specialist outputs conflict, a recorded CEO decision with a rationale and supporting inputs exists in 100% of conflict cases; where the conflict meets the escalation criteria, a human escalation is recorded.
- **SC-015**: The mandatory concurrency test and the mandatory end-to-end CEO test (objective → plan → parallel execution → dependent waiting → conflict handling → recommendation, with every major event persisted and audited) both pass.
- **SC-016**: The mandatory Agent Settings test passes: view prompt → view active version → create version → review diff → select provider → select valid model → test → activate → verify audit entry → run agent → confirm the configured provider/model was used; and a second agent left on default is unchanged.
- **SC-017**: The mandatory failure test passes: a simulated agent failure results in a failed task, a CEO failure event, retry per policy, human notification on repeated failure, no false completion of dependents, a truthful console, and an audit record.
- **SC-018**: The mandatory provider-failure test passes: with a provider unavailable, routing falls back, the console shows the provider actually used, and a fallback is recorded where applicable.
- **SC-019**: The continuous-integration pipeline is green on a clean checkout (data seeding included); the only excluded checks are environment-only third-party failures explicitly quarantined from the default gate.
- **SC-020**: Zero regressions: all pre-existing user-facing dashboards, authenticated routes, and test suites that passed before this feature continue to pass; every intentional behavioural change is covered by a test.
- **SC-021**: An owner interacting only through stating objectives and reviewing the console can run a full research cycle end-to-end (objective → plan → parallel work → dependent work → conflict resolution → recommendation → approval) without performing any step manually in a dashboard.
- **SC-023**: An application restart during an in-progress organization run results in the run resuming automatically from its last completed task, with zero completed tasks re-executed and zero artefacts regenerated, verifiable from the run's recorded task timeline.
- **SC-022**: An objective submitted via a connected messaging channel results in a real Organizational Plan and a CEO-synthesis reply for that run in 100% of orchestration-warranting cases; a pure data lookup does not create a run.

---

## Assumptions

- **A-1 (Feature framing)**: The transformation is treated as one feature delivered through the prioritised, independently shippable user stories above. US1–US4 (P1) constitute the minimum viable "CEO-led organisation"; US5–US8 (P2) deliver the premium command-centre and configuration surfaces; US9 (P3) hardens control enforcement. Detailed design artefacts (the 28-document spec-kit tree, architecture deltas, database DDL, endpoint contracts, component trees, 16-phase roadmap) are produced by `/speckit-plan` and subsequent commands, not by this spec.
- **A-2 (Audit baseline)**: `docs/audit-2026-09.md` (findings BUG-A … BUG-I and the P0–P3 remediation plan) is authoritative for current-state gaps and is the implementation backlog. Where the audit, the design documents, the codebase, and this brief disagree, the discrepancy is called out in `/speckit-plan`'s current-state analysis rather than silently resolved.
- **A-3 (Visual reference)**: The `multi-agent-ai-console.zip` referenced in the brief is not present in the working tree at spec time. It is treated as a **design inspiration input for `/speckit-plan` / design phase only** — layout, panel density, dark operations aesthetic, status indicators, settings patterns, interaction and animation ideas. Its product name, sample data, business model, and application semantics are explicitly out of scope. If the archive is not supplied, the design phase proceeds from the brief's written visual direction (§32, §75) and the existing TradingOS design system. This is a dependency, not a blocker.
- **A-4 (Design system)**: The console follows the brief's stated direction — dark premium panels, fine borders, restrained accents, semantic green/amber/red, compact data density, animation used only to communicate state (running pulse, waiting indicator, dependency-line activation, hand-off transition, completion transition) — reconciled with the existing TradingOS visual language.
- **A-5 (Safety architecture unchanged)**: The deterministic risk engine, kill switch, compliance checks, RBAC model, broker controls, and immutable audit chain are reused as-is and are never subordinate to the organisational layer. Business Rule 1 (kill switch supremacy) and Business Rule 3 (human approval for live capital) are unchanged.
- **A-6 (Foundation reuse)**: LangGraph, the LLM router and its routing policy, the SkillRegistry, the execution sandbox, the vector memory, the cache/pub-sub bus, the relational store, the scheduler, the audit architecture, and the existing frontend foundations are extended, not replaced. The existing research pipeline's proven engines are refactored into organisational tasks.
- **A-7 (AUTO default)**: "AUTO" provider/model means the agent uses the existing configured routing policy unchanged. Shipping this feature must not alter any agent's default model behaviour; custom overrides are strictly opt-in per agent.
- **A-8 (Concurrency safety)**: "Run independent tasks concurrently where technically safe" excludes operations that would race on shared mutable state (e.g. a single global kill-switch singleton, a shared sandbox worker that cannot be safely shared). Such operations remain serialised; the plan documents which task types are concurrency-eligible.
- **A-9 (Data freshness scope)**: Fixing the ingestion cadence so real market data is fresh is in scope for US7. The specific cadence (e.g. nightly end-of-day) and the freshness threshold are set in `/speckit-plan` against the Indian market calendar; the requirement here is that they are defined, enforced, checksum-validated, visible, and alerted.
- **A-10 (Regulatory data)**: A live SEBI position-limit / circuit-filter feed is assumed to remain unavailable (no such public interface exists). Compliance continues with its documented limited-coverage reference data; the limitation, coverage, fallback, and governance implication are surfaced rather than hidden. This feature does not require obtaining such a feed.
- **A-11 (Environment)**: The single hardened Docker Compose host is production (per the project constitution and Phase 1 ADR 10). No separate staging environment is assumed. All checks and demos run against that single environment.
- **A-12 (MFA)**: Multi-factor authentication enforcement for privileged roles is a known, separately-tracked item pending human enrolment. This feature assumes RBAC is enforced; it does not depend on MFA being enabled, and it does not itself enable MFA.
- **A-13 (Tenancy)**: A tenancy model exists (single seeded primary tenant). Task and run records carry a tenant reference for forward-compatibility; multi-tenant isolation behaviour beyond what already exists is out of scope for this feature.
- **A-14 (Objective source & authorisation)**: Objectives may originate from an authenticated owner in the web app, from the scheduler, or from a connected messaging channel whose sender has been mapped to an authorised identity. Unmapped or unauthorised senders' messages are recorded but do not create organisational work.
- **A-15 (Live-update transport)**: Live console updates use the existing WebSocket/event streaming infrastructure. The 2-second visibility target in SC-007 is a goal for normal load on the single host, not a hard NFR; the hard requirement is "live, no manual refresh, re-syncs on reconnect."
- **A-16 (Chain-of-thought)**: Wherever the brief asks to show "CEO thinking", the product shows an **operational activity narrative** derived from real state transitions and decisions. Private model chain-of-thought is never surfaced.

## Dependencies

- Existing TradingOS backend (LangGraph orchestration, LLM router + `routing.yaml`, SkillRegistry, sandbox, deterministic risk engine, compliance checker, audit chain, scheduler), relational store, vector memory, cache/pub-sub bus, and observability stack.
- Existing frontend application and its authenticated route structure and design system.
- `docs/audit-2026-09.md` as the current-state and backlog baseline.
- The project constitution (`.specify/memory/constitution.md`) — in particular the safety-critical-controls, real-integrations/honest-status, module-storage-ownership, and quality-gates principles.
- (Optional) `multi-agent-ai-console.zip` visual reference — design-phase input only; absence does not block.

---

## Audit Traceability

| Audit finding | Summary | Addressed by (story) | Key FRs | Verified by |
|---|---|---|---|---|
| BUG-A | Stale market data → autonomous run cannot complete (freshness gate rejects real symbols) | US7 | FR-060…FR-064, FR-062, A-9 | SC-006, SC-019 |
| BUG-B | HITL "approve" is a post-hoc annotation; strategy auto-enters Paper Trading | US3 | FR-052…FR-057 | SC-003 |
| BUG-C | News / Sentiment / Portfolio agent outputs consumed by nothing | US4, US5 | FR-031, FR-040…FR-044, FR-082, FR-086 | SC-004, SC-005, SC-009 |
| BUG-D | `fetch_global_indices`, `query_news_sentiment` (and macro calendar) stubbed | US4, US8 | FR-070, FR-071 | SC-005 (context completeness), plan-level skill tests |
| BUG-E | CI not green on a clean checkout | (cross-cutting) | FR-161 | SC-019 |
| BUG-F | Live execution pipeline does not persist order records | (cross-cutting, guards FR-050/56) | FR-162 | Plan-level reconciliation test |
| BUG-G | Stale Agent Console caption / hard-coded status text | US5 | FR-081, FR-089 | SC-008 |
| BUG-H | Stale developer docstrings ("no scheduler exists", "no such feature") | (cross-cutting) | FR-163 | Plan-level doc review |
| BUG-I | Documented agent lifecycle states not modelled in run status | US2 | FR-011, FR-012 | SC-002, SC-015 |
| Agent-control enforcement gap | Several agents' enable/disable state stored but never checked | US9 | FR-120…FR-122 | SC-013 |
| CEO emits a directive consumed linearly; no task/plan model | Core architectural gap | US1, US2 | FR-002…FR-008, FR-010…FR-018 | SC-001, SC-002, SC-015, SC-021 |
| No cross-agent delegation / review / conflict handling | Core architectural gap | US2 (collab), US4 | FR-020…FR-023 | SC-014, SC-015 |
| Incomplete omni-channel research trigger; no conversational analytical agents | Agent-first gaps | US8 | FR-130…FR-134 | SC-022 |
| Observability limitations | No org-level event model / run replay | US5 | FR-140…FR-142, FR-087 | SC-007, SC-015 |
| Provider/model not per-agent configurable; prompt edits need redeploy | New requirement (brief §44–§53) | US6 | FR-100…FR-110 | SC-010, SC-011, SC-012, SC-016 |
| P0 (audit): prove one unbroken end-to-end run | Core proof | US1, US2, US7 | FR-003, FR-013, FR-014, FR-062 | SC-015, SC-021 |
| P1/P2/P3 (audit) | Remaining prioritised backlog | Distributed across US1–US9 | see per-row above | see per-row above |
