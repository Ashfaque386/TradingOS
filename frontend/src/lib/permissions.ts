// REL-011 E11.3: central RBAC permission table for client-side gating. Every entry mirrors an
// exact server-side `require_role(...)` call site -- this table can never be the real security
// boundary (that's Casbin/policy.csv, enforced server-side), it only decides what a control
// looks like in the UI so an ineligible role never sees or triggers something that will 403.

import { ROLES, type Role } from "@/lib/api";

export const PERMISSIONS = {
  // src/api/routers/system.py -- kill-switch trip/reset.
  killSwitch: [ROLES.SystemAdministrator, ROLES.PortfolioManager, ROLES.RiskManager],
  // src/api/routers/strategies.py:_can_promote -- POST /strategies/{id}/promote.
  promoteStrategy: [ROLES.SystemAdministrator, ROLES.PortfolioManager],
  // src/api/routers/settings.py -- notification-channel CRUD.
  manageNotificationChannels: [ROLES.SystemAdministrator, ROLES.PortfolioManager],
  // src/api/routers/agents.py:_can_manage_hitl -- POST /agents/runs/{id}/retry|approve|reject.
  manageHitl: [ROLES.SystemAdministrator, ROLES.PortfolioManager, ROLES.RiskManager],
  // src/api/routers/audit.py:_can_read_audit -- GET /audit/*.
  readAudit: [ROLES.SystemAdministrator, ROLES.ReadOnlyAuditor],
  // src/api/routers/agents.py:_can_manage_hitl -- POST /agents/research/trigger (REL-011
  // E10.11.0 closed this route's previously-nonexistent auth dependency).
  triggerResearch: [ROLES.SystemAdministrator, ROLES.PortfolioManager, ROLES.RiskManager],
  // src/api/routers/agents.py:_can_manage_hitl -- PUT /agents/prompts/{slug}/active-version
  // (REL-011 E10.11.0).
  swapActivePrompt: [ROLES.SystemAdministrator, ROLES.PortfolioManager, ROLES.RiskManager],
  // src/api/routers/strategies.py:_can_trigger_backtest -- POST /strategies/{id}/backtest
  // (REL-011 E10.11.0).
  triggerBacktest: [ROLES.SystemAdministrator, ROLES.PortfolioManager, ROLES.RiskManager],
  // src/api/routers/risk_limits.py:_can_stage_or_confirm -- POST .../change-requests,
  // .../confirm, .../reject (REL-017 E17.1). PortfolioManager deliberately excluded, matching
  // the router's own docstring on RiskLimit.set_by_user_id being SA/RiskManager only.
  manageRiskLimits: [ROLES.SystemAdministrator, ROLES.RiskManager],
  // src/api/routers/broker_config.py:_can_manage_broker_credentials -- POST/DELETE
  // /broker/credentials/{broker} (REL-017 E17.2).
  manageBrokerCredentials: [ROLES.SystemAdministrator],
  // src/api/routers/settings.py:_can_manage_llm_keys -- POST/DELETE
  // /settings/llm-provider-keys/{provider} (REL-021 E21.1).
  manageLlmProviderKeys: [ROLES.SystemAdministrator],
  // src/api/routers/agent_settings.py:_can_manage -- POST /agents/{slug}/config/prompts/*,
  // PUT .../provider-model, POST .../test (spec 001-ceo-led-trading-org US6, clarify Q4). SA only.
  manageAgentConfig: [ROLES.SystemAdministrator],
  // src/api/routers/agents.py:_can_manage_hitl -- PUT /agents/control/{agent_name}
  // (REL-019 E19.2, ADR 11). Same role set as manageHitl since disabling a pipeline agent is an
  // equivalent-weight operational action to approving/rejecting a run.
  manageAgentControl: [ROLES.SystemAdministrator, ROLES.PortfolioManager, ROLES.RiskManager],
  // src/api/routers/strategies.py:_can_review_suggestion -- POST
  // /strategies/{id}/suggestions/{suggestion_id}/review (REL-048). Same role set as
  // triggerBacktest since a review re-enters the real agent pipeline (real LLM calls, a real
  // sandboxed backtest) -- an equivalent-weight operational action. Submitting a suggestion
  // itself needs no permission key here: it's open to any authenticated user server-side.
  reviewStrategySuggestion: [ROLES.SystemAdministrator, ROLES.PortfolioManager, ROLES.RiskManager],
  // src/api/routers/scheduled_jobs.py:_can_view_scheduled_jobs -- GET /scheduled-jobs* (REL-081).
  // Broader than readAudit's SA+Auditor-only set: this is status/history visibility, not raw
  // audit-log content.
  viewScheduledJobs: [
    ROLES.SystemAdministrator,
    ROLES.ReadOnlyAuditor,
    ROLES.PortfolioManager,
    ROLES.RiskManager,
  ],
  // src/api/routers/scheduled_jobs.py:_can_manage_scheduled_jobs -- PUT /scheduled-jobs/{job_id}
  // (REL-081). SA/PM/RM, matching manageAgentControl's own precedent -- a schedule edit is
  // treated as an equivalent-weight operational action, not a compliance-tier one (revised from
  // an initial SA-only gate after the user asked for it to be broadened).
  manageScheduledJobs: [ROLES.SystemAdministrator, ROLES.PortfolioManager, ROLES.RiskManager],
  // src/api/routers/scheduled_jobs.py:_can_manage_scheduled_jobs -- POST
  // /scheduled-jobs/{job_id}/run-now (REL-081). Same gate as manageScheduledJobs.
  runScheduledJobNow: [ROLES.SystemAdministrator, ROLES.PortfolioManager, ROLES.RiskManager],
} as const satisfies Record<string, readonly Role[]>;

export type PermissionKey = keyof typeof PERMISSIONS;
