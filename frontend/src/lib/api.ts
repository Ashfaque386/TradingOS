const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8001";
// Exported so callers can build a real, actionable message when a request never reaches this
// origin at all (e.g. a self-signed TLS cert the browser hasn't been told to trust yet) --
// see login/page.tsx's own CONNECTION_ERROR_MESSAGE for the concrete case this closes.
export { API_BASE };

export const WS_BASE = API_BASE.replace(/^http/, "ws");

// Canonical role strings -- must match src/core/security.py's ALL_ROLES exactly (Phase 4
// exit-criteria gap: RBAC, Phase_12_Security_Design.md §2.2's permission matrix).
export const ROLES = {
  SystemAdministrator: "SystemAdministrator",
  PortfolioManager: "PortfolioManager",
  RiskManager: "RiskManager",
  ReadOnlyAuditor: "ReadOnlyAuditor",
} as const;
export type Role = (typeof ROLES)[keyof typeof ROLES];

// Set by AuthProvider (lib/auth.tsx) on login/logout/initial-load. A module-level variable
// rather than something read from React state, since the get/post/etc. helpers below are plain
// async functions, not hooks -- they have no component tree to read context from.
let authToken: string | null = null;
export function setAuthToken(token: string | null): void {
  authToken = token;
}
function authHeaders(): Record<string, string> {
  return authToken ? { Authorization: `Bearer ${authToken}` } : {};
}

export interface Position {
  symbol: string;
  net_quantity: number;
  average_price: number | null;
  last_price: number | null;
  unrealized_pnl: number;
  realized_pnl: number;
}

export interface Margin {
  available_margin: number;
  used_margin: number;
  raw: Record<string, unknown>;
}

export interface PnLResponse {
  unrealized_pnl: number;
  realized_pnl: number;
  total_pnl: number;
  daily_loss_limit: number | null;
  pct_of_daily_limit_used: number | null;
}

export interface RiskMetricsResponse {
  sharpe_ratio: number | null;
  sharpe_ratio_source: "backtest" | "unavailable";
  beta_vs_nifty50: number | null;
  daily_pnl: number;
  daily_loss_limit: number | null;
  pct_of_daily_limit_used: number | null;
  max_sector_exposure_pct: number | null;
}

export interface SymbolExposure {
  symbol: string;
  market_value: number;
  pct_of_gross: number;
}

export interface AllocationResponse {
  by_symbol: SymbolExposure[];
  gross_exposure: number;
  sector_data_available: boolean;
  strategy_data_available: boolean;
}

export interface KillSwitchStatus {
  state: "ARMED" | "TRIPPED";
  tripped_at: string | null;
}

export interface PortfolioTick {
  pnl: number;
  drawdown: number | null;
  margin_used: number;
  ts: string;
}

export interface GraphNode {
  id: string;
}

export interface GraphEdge {
  source: string;
  target: string;
  conditional: boolean;
}

export interface GraphTopology {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface TriggerResponse {
  run_id: string;
  thread_id: string;
  status: string;
}

export interface AgentRunSummary {
  run_id: string;
  thread_id: string;
  agent_name: string;
  status: string;
  started_at: string;
  ended_at: string | null;
  human_decision: string | null;
}

export interface AgentLogEntry {
  node: string;
  log_level: string;
  message: string;
  created_at: string;
}

export interface AgentRunDetail extends AgentRunSummary {
  nodes: AgentRunSummary[];
  logs: AgentLogEntry[];
}

// REL-019 E19.2 (ADR 11): src/agents/control.py::KNOWN_AGENTS joined against the real
// agent_control_state table -- `enforced` tells the UI honestly whether a real call site
// checks this agent's state today, not just whether the toggle itself is real (it always is).
export interface AgentControlEntry {
  agent_name: string;
  agent_id: string;
  display_name: string;
  kind: "graph_node" | "scheduled" | "registry_only";
  enforced: boolean;
  enabled: boolean;
  reason: string | null;
  updated_by: string | null;
  updated_at: string | null;
}

export interface PromptSummary {
  agent_slug: string;
  prompt_id: string;
  active_version: number;
  available_versions: number[];
}

export interface PromptVersionContent {
  agent_slug: string;
  version: number;
  content: string;
}

export interface AgentLogStreamMessage {
  agent_id: string;
  node: string;
  message: string;
  ts: string;
}

export type StrategyStatus = "Ideation" | "Coding" | "Backtesting" | "PaperTrading" | "Live" | "Deprecated";

export interface StrategySummary {
  id: string;
  name: string;
  hypothesis: string | null;
  asset_class: string;
  style: string;
  status: StrategyStatus;
  universe: string[] | null;
  current_version_id: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface StrategyVersionSummary {
  id: string;
  version_no: number;
  validation_status: string;
  validator_feedback: string | null;
}

export interface BacktestSummary {
  id: string;
  strategy_version_id: string;
  date_from: string;
  date_to: string;
  sharpe_ratio: number | null;
  sortino_ratio: number | null;
  calmar_ratio: number | null;
  max_drawdown: number | null;
  cagr: number | null;
  win_rate: number | null;
  profit_factor: number | null;
  expectancy: number | null;
  total_trades: number | null;
  has_equity_curve: boolean;
  // REL-017 E17.4 (DB-007): real column. UPDATE 2026-08-05 (REL-023): a real Monte Carlo
  // simulation now runs against real per-trade returns (REL-022) for every newly-triggered
  // backtest -- still null for backtests created before this release (not backfilled) or with
  // fewer than 2 usable returns either way, exposed honestly rather than hidden.
  monte_carlo_p95_max_drawdown: number | null;
  created_at: string;
}

export interface StrategyDetail extends StrategySummary {
  versions: StrategyVersionSummary[];
  backtests: BacktestSummary[];
}

export interface VersionCode {
  version_no: number;
  python_code: string;
}

export interface BacktestTriggerResponse {
  job_id: string;
  status: string;
}

export interface BacktestJobStatus {
  job_id: string;
  status: "Running" | "Completed" | "Failed";
  error: string | null;
  backtest_result_id: string | null;
}

export interface EquityCurvePoint {
  date: string;
  equity: number;
}

// REL-023 E23.2: real per-trade ledger (REL-022's sandbox contract extension), stored directly
// on the BacktestResult row -- no separate file, unlike the equity curve.
export interface TradeSummary {
  entry_date: string;
  exit_date: string;
  side: "long" | "short";
  size: number;
  entry_price: number;
  exit_price: number;
  pnl: number;
  return_pct: number;
}

// REL-024 E24.3: real Walk-Forward Optimization window summaries (src/engine/optimization/
// walk_forward_adapter.py), stored directly on the BacktestResult row like TradeSummary above.
export interface WalkForwardWindow {
  train_start: string;
  train_end: string;
  test_start: string;
  test_end: string;
  train_expectancy: number | null;
  test_expectancy: number | null;
  test_sharpe_ratio: number | null;
  test_total_trades: number | null;
  out_of_sample_passed: boolean;
}

export interface ProviderStatus {
  name: string;
  configured: boolean;
  masked_hint: string | null;
}

export interface BrokerStatus extends ProviderStatus {
  sandbox: boolean | null;
}

export interface IntegrationsStatus {
  llm_providers: ProviderStatus[];
  brokers: BrokerStatus[];
  editable: boolean;
}

// REL-017 E17.1: src/api/routers/risk_limits.py's dual-control stage/confirm/reject workflow.
export interface CurrentRiskLimit {
  scope_type: string;
  max_daily_loss: number;
  max_position_size_pct: number | null;
  max_sector_exposure_pct: number | null;
  max_drawdown_pct: number | null;
  effective_from: string;
}

export interface RiskLimitChangeRequest {
  id: string;
  status: "PENDING" | "APPROVED" | "REJECTED";
  scope_type: string;
  max_daily_loss: number;
  staged_by_user_id: string;
  confirmed_by_user_id: string | null;
  resulting_risk_limit_id: string | null;
}

export interface RiskLimitChangePayload {
  scope_type: string;
  scope_id?: string;
  max_daily_loss: number;
  max_position_size_pct?: number;
  max_sector_exposure_pct?: number;
  max_drawdown_pct?: number;
  effective_from: string;
}

// REL-017 E17.2: src/api/routers/broker_config.py -- write-only, never round-trips a real secret.
export type BrokerId = "zerodha" | "upstox";

// REL-021 E21.1: src/api/routers/settings.py::LLM_PROVIDER_IDS -- write-only, same as BrokerId.
export type LlmProviderId =
  | "openai"
  | "anthropic"
  | "deepseek"
  | "gemini"
  | "huggingface"
  | "opencode";

export const ALERT_LEVELS = [
  "critical_errors",
  "executed_trades",
  "risk_warnings",
  "strategy_promotions",
] as const;
export type AlertLevel = (typeof ALERT_LEVELS)[number];

export type ChannelType = "Telegram" | "Discord" | "Slack" | "Email";

export interface NotificationChannel {
  id: string;
  channel_type: ChannelType;
  external_handle: string;
  is_verified: boolean;
  preferences: { alert_levels?: AlertLevel[] };
}

export type ChatMessageStatus = "Pending" | "Completed" | "Failed";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  status: ChatMessageStatus;
  error: string | null;
  created_at: string;
}

export interface LatestCode {
  strategy_id: string;
  strategy_name: string;
  version_no: number;
  python_code: string;
  validation_status: string;
  created_at: string;
}

export interface LatestBacktest {
  backtest_id: string;
  strategy_id: string;
  strategy_name: string;
  sharpe_ratio: number | null;
  max_drawdown: number | null;
  total_trades: number | null;
  has_equity_curve: boolean;
  created_at: string;
}

export interface LatestAgentActivity {
  node: string;
  message: string;
  created_at: string;
}

export interface CanvasState {
  latest_code: LatestCode | null;
  latest_backtest: LatestBacktest | null;
  latest_agent_activity: LatestAgentActivity | null;
}

/** REL-011 E11.4a: first endpoint set needing optional query params from the frontend --
 * builds `?a=1&b=2`, skipping undefined/null values, empty string otherwise. */
function toQuery(params?: Record<string, string | number | undefined>): string {
  if (!params) return "";
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store", headers: authHeaders() });
  if (!res.ok) {
    throw new Error(`GET ${path} failed: ${res.status} ${await res.text()}`);
  }
  return res.json() as Promise<T>;
}

/** REL-017: a 204 No Content response (e.g. POST /broker/credentials/{broker}) has no body --
 * calling res.json() on it throws, so this variant is for POST endpoints that return nothing. */
async function postNoContent(path: string, body?: unknown): Promise<void> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    throw new Error(`POST ${path} failed: ${res.status} ${await res.text()}`);
  }
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    throw new Error(`POST ${path} failed: ${res.status} ${await res.text()}`);
  }
  return res.json() as Promise<T>;
}

async function put<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(`PUT ${path} failed: ${res.status} ${await res.text()}`);
  }
  return res.json() as Promise<T>;
}

async function patch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(`PATCH ${path} failed: ${res.status} ${await res.text()}`);
  }
  return res.json() as Promise<T>;
}

async function del(path: string): Promise<void> {
  const res = await fetch(`${API_BASE}${path}`, { method: "DELETE", headers: authHeaders() });
  if (!res.ok) {
    throw new Error(`DELETE ${path} failed: ${res.status} ${await res.text()}`);
  }
}

/** REL-011 E11.4a: a plain `<a href>` GET can't attach a Bearer header, and audit export
 * (`_can_read_audit`) genuinely requires one -- fetches the file as a Blob and triggers a
 * synthetic download instead. */
export async function downloadAuthenticated(path: string, filename: string): Promise<void> {
  const res = await fetch(`${API_BASE}${path}`, { headers: authHeaders() });
  if (!res.ok) {
    throw new Error(`GET ${path} failed: ${res.status} ${await res.text()}`);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

// Explicit-token variant of post() -- used for the 3 MFA endpoints below, which authenticate
// with a short-lived pending-MFA token (returned by /auth/login, not yet a real session), not
// the module-level authToken a logged-in user's normal requests carry.
async function postWithToken<T>(path: string, token: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    throw new Error(`POST ${path} failed: ${res.status} ${await res.text()}`);
  }
  return res.json() as Promise<T>;
}

// REL-007 E7.1/E7.3: SystemAdministrator/PortfolioManager/RiskManager now require MFA, and a
// real session includes a refresh_token alongside the access_token -- access_token/refresh_token
// are null exactly when mfa_required is true (the credential was correct, but no real session
// exists yet until /mfa/confirm or /mfa/verify succeeds).
export interface LoginResponse {
  access_token: string | null;
  refresh_token: string | null;
  token_type: string;
  user_id: string;
  role: Role;
  mfa_required: boolean;
  mfa_enrolled: boolean;
  pending_token: string | null;
}

export interface MfaEnrollResponse {
  secret_base32: string;
  otpauth_uri: string;
  backup_codes: string[];
}

export interface MfaSessionResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user_id: string;
  role: Role;
}

export interface CurrentUser {
  id: string;
  email: string;
  full_name: string | null;
  role: Role;
}

// REL-011 E11.4a -- src/api/routers/audit.py's real response models.
export interface AuditLogEntry {
  id: number;
  actor_type: string;
  actor_id: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  before_state: Record<string, unknown> | null;
  after_state: Record<string, unknown> | null;
  ip_address: string | null;
  created_at: string;
  entry_hash: string;
  prev_entry_hash: string;
}

export interface TradeAuditTrace {
  entity_id: string;
  entries: AuditLogEntry[];
}

export interface ActorAuditSummary {
  actor_id: string;
  total_entries: number;
  action_counts: Record<string, number>;
  first_entry_at: string;
  last_entry_at: string;
}

// REL-011 E11.4b -- src/api/routers/agents.py's real HITL response models.
export interface RetryResponse {
  run_id: string;
  retried_from_run_id: string;
  thread_id: string;
  status: string;
}

export interface HitlDecisionResponse {
  run_id: string;
  human_decision: string;
  strategy_id: string | null;
  strategy_status: string | null;
}

// REL-011 E11.1 -- src/api/routers/market_data.py's real response models.
export interface OhlcvBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

// REL-013 -- src/api/routers/paper_trading.py's real response models. Every row is a real
// depth-walked simulated fill against a real live broker quote; nothing here ever calls
// place_order (src/engine/paper_trading/execution_service.py).
export interface PaperTrade {
  id: string;
  account_id: string;
  strategy_id: string | null;
  instrument_type: string;
  symbol: string;
  side: "BUY" | "SELL";
  requested_quantity: number;
  filled_quantity: number;
  reference_price: number;
  fill_price: number;
  slippage_bps: number;
  executed_at: string;
}

export interface PaperPosition {
  symbol: string;
  net_quantity: number;
  average_cost: number | null;
  realized_pnl: number;
  trade_count: number;
}

// REL-034: the Paper Trading Account's real broker-style summary/report -- see
// src/api/routers/paper_trading.py's own /account/* endpoints.
export interface AccountSummary {
  account_id: string;
  starting_capital: number;
  cash: number;
  margin_blocked: number;
  realized_pnl_total: number;
  unrealized_pnl_total: number;
  realized_pnl_by_instrument_class: Record<string, number>;
  equity: number;
}

export interface EquityCurvePoint {
  snapshot_date: string;
  equity: number;
  cash: number;
  unrealized_pnl: number;
  margin_blocked: number;
}

// REL-018 E18.1 -- src/api/routers/orders.py's real response models, over the real (live)
// ORDERS/TRADES tables (DB-008/009), not the paper ledger above.
export interface LiveOrder {
  id: string;
  strategy_id: string;
  symbol: string;
  side: string;
  order_type: string;
  quantity: number;
  limit_price: number | null;
  status: string;
  requested_at: string;
  acknowledged_at: string | null;
  latency_ms: number | null;
  rejection_reason: string | null;
}

export interface LiveTrade {
  id: string;
  order_id: string;
  strategy_id: string;
  symbol: string;
  side: string;
  price: number;
  quantity: number;
  brokerage: number;
  stt: number;
  gst: number;
  net_pnl: number | null;
  executed_at: string;
}

export interface ExecutionLatencySummary {
  sample_count: number;
  total_seconds: number;
  avg_ms: number | null;
}

// REL-013 -- src/api/routers/shadow_mode.py's real response models. Broker-honest: Upstox
// attempts hit a real sandbox order call, Zerodha attempts are local-only payload validation
// (Kite Connect has no sandbox at all) -- see src/brokers/shadow_mode.py.
export interface ShadowDailySummary {
  date: string;
  attempts: number;
  errors: number;
  clean: boolean;
}

export interface ShadowModeStatus {
  consecutive_clean_days: number;
  go_live_gate_met: boolean;
  daily_summary: ShadowDailySummary[];
}

// REL-013 -- src/api/routers/go_live_readiness.py's real response model
// (src/engine/go_live_gate.py's 4-condition authoritative gate).
export interface GateCondition {
  label: string;
  met: boolean;
  detail: string;
}

export interface GoLiveReadiness {
  strategy_id: string;
  gate_met: boolean;
  conditions: GateCondition[];
}

export const api = {
  login: (email: string, password: string) =>
    post<LoginResponse>("/api/v1/auth/login", { email, password }),
  me: () => get<CurrentUser>("/api/v1/auth/me"),
  logout: (refreshToken: string) => post<{ status: string }>("/api/v1/auth/logout", { refresh_token: refreshToken }),

  mfaEnroll: (pendingToken: string) =>
    postWithToken<MfaEnrollResponse>("/api/v1/auth/mfa/enroll", pendingToken),
  mfaConfirm: (pendingToken: string, totpCode: string) =>
    postWithToken<MfaSessionResponse>("/api/v1/auth/mfa/confirm", pendingToken, {
      totp_code: totpCode,
    }),
  mfaVerify: (pendingToken: string, body: { totp_code?: string; backup_code?: string }) =>
    postWithToken<MfaSessionResponse>("/api/v1/auth/mfa/verify", pendingToken, body),

  positions: () => get<Position[]>("/api/v1/positions"),
  margin: () => get<Margin>("/api/v1/portfolio/margin"),
  pnl: () => get<PnLResponse>("/api/v1/portfolio/pnl"),
  riskMetrics: () => get<RiskMetricsResponse>("/api/v1/portfolio/risk-metrics"),
  allocation: () => get<AllocationResponse>("/api/v1/portfolio/allocation"),
  killSwitchStatus: () => get<KillSwitchStatus>("/api/v1/system/kill-switch/status"),
  tripKillSwitch: (reason: string) =>
    post<{ status: string; liquidated_positions: number }>("/api/v1/system/kill-switch", {
      reason,
    }),
  resetKillSwitch: () =>
    post<{ status: string }>("/api/v1/system/kill-switch/reset", { confirmation: true }),

  graphTopology: () => get<GraphTopology>("/api/v1/agents/graph"),
  triggerResearch: () => post<TriggerResponse>("/api/v1/agents/research/trigger"),
  runs: () => get<AgentRunSummary[]>("/api/v1/agents/runs"),
  run: (runId: string) => get<AgentRunDetail>(`/api/v1/agents/runs/${runId}`),
  prompts: () => get<PromptSummary[]>("/api/v1/agents/prompts"),
  promptVersion: (slug: string, version: number) =>
    get<PromptVersionContent>(`/api/v1/agents/prompts/${slug}/versions/${version}`),
  setActivePromptVersion: (slug: string, version: number) =>
    put<PromptSummary>(`/api/v1/agents/prompts/${slug}/active-version`, { version }),

  agentControlList: () => get<AgentControlEntry[]>("/api/v1/agents/control"),
  setAgentEnabled: (agentName: string, enabled: boolean, reason: string | null) =>
    put<AgentControlEntry>(`/api/v1/agents/control/${agentName}`, { enabled, reason }),

  strategies: () => get<StrategySummary[]>("/api/v1/strategies"),
  strategy: (id: string) => get<StrategyDetail>(`/api/v1/strategies/${id}`),
  strategyVersionCode: (id: string, versionNo: number) =>
    get<VersionCode>(`/api/v1/strategies/${id}/versions/${versionNo}`),
  triggerBacktest: (id: string) =>
    post<BacktestTriggerResponse>(`/api/v1/strategies/${id}/backtest`),
  backtestJobStatus: (jobId: string) =>
    get<BacktestJobStatus>(`/api/v1/strategies/backtests/jobs/${jobId}/status`),
  equityCurve: (backtestId: string) =>
    get<EquityCurvePoint[]>(`/api/v1/strategies/backtests/${backtestId}/equity-curve`),
  backtestTrades: (backtestId: string) =>
    get<TradeSummary[]>(`/api/v1/strategies/backtests/${backtestId}/trades`),
  backtestWalkForward: (backtestId: string) =>
    get<WalkForwardWindow[]>(`/api/v1/strategies/backtests/${backtestId}/walk-forward`),
  promoteStrategy: (id: string, toStatus: StrategyStatus) =>
    post<StrategySummary>(`/api/v1/strategies/${id}/promote`, { to_status: toStatus }),

  integrationsStatus: () => get<IntegrationsStatus>("/api/v1/settings/integrations"),
  notificationChannels: () =>
    get<NotificationChannel[]>("/api/v1/settings/notification-channels"),
  createNotificationChannel: (body: {
    channel_type: ChannelType;
    external_handle: string;
    alert_levels: AlertLevel[];
  }) => post<NotificationChannel>("/api/v1/settings/notification-channels", body),
  updateNotificationChannel: (
    id: string,
    body: { external_handle?: string; is_verified?: boolean; alert_levels?: AlertLevel[] },
  ) => patch<NotificationChannel>(`/api/v1/settings/notification-channels/${id}`, body),
  deleteNotificationChannel: (id: string) =>
    del(`/api/v1/settings/notification-channels/${id}`),

  chatMessages: () => get<ChatMessage[]>("/api/v1/chat/messages"),
  sendChatMessage: (content: string) =>
    post<ChatMessage>("/api/v1/chat/messages", { content }),
  canvasState: () => get<CanvasState>("/api/v1/canvas/state"),

  auditLogs: (params?: { entity_type?: string; actor_id?: string; limit?: number }) =>
    get<AuditLogEntry[]>(`/api/v1/audit/logs${toQuery(params)}`),
  auditLog: (id: number) => get<AuditLogEntry>(`/api/v1/audit/logs/${id}`),
  tradeTrace: (entityId: string) =>
    get<TradeAuditTrace>(`/api/v1/audit/trades/${entityId}/trace`),
  actorSummary: (actorId: string) =>
    get<ActorAuditSummary>(`/api/v1/audit/actors/${actorId}/summary`),
  auditExportPath: (params: {
    export_format: "csv" | "ndjson";
    entity_type?: string;
    limit?: number;
  }) => `/api/v1/audit/export${toQuery(params)}`,

  retryRun: (runId: string) => post<RetryResponse>(`/api/v1/agents/runs/${runId}/retry`),
  approveRun: (runId: string) =>
    post<HitlDecisionResponse>(`/api/v1/agents/runs/${runId}/approve`),
  rejectRun: (runId: string, reason: string) =>
    post<HitlDecisionResponse>(`/api/v1/agents/runs/${runId}/reject`, { reason }),

  // encodeURIComponent: REL-017 needed this for the real "^NSEI" Nifty 50 benchmark symbol --
  // a literal "^" in a template-string URL is not itself invalid, but this is the correct fix
  // for any symbol containing a URL-meaningful character, not just this one.
  ohlcv: (symbol: string) => get<OhlcvBar[]>(`/api/v1/market/ohlcv/${encodeURIComponent(symbol)}`),
  symbols: () => get<string[]>("/api/v1/market/symbols"),

  paperTrades: (strategyId?: string) =>
    get<PaperTrade[]>(`/api/v1/paper-trading/trades${toQuery({ strategy_id: strategyId })}`),
  paperPositions: (strategyId?: string) =>
    get<PaperPosition[]>(`/api/v1/paper-trading/positions${toQuery({ strategy_id: strategyId })}`),

  accountSummary: () => get<AccountSummary>("/api/v1/paper-trading/account/summary"),
  accountEquityCurve: (from?: string, to?: string) =>
    get<EquityCurvePoint[]>(
      `/api/v1/paper-trading/account/equity-curve${toQuery({ from, to })}`,
    ),

  orders: (strategyId?: string) =>
    get<LiveOrder[]>(`/api/v1/orders${toQuery({ strategy_id: strategyId })}`),
  trades: (strategyId?: string) =>
    get<LiveTrade[]>(`/api/v1/trades${toQuery({ strategy_id: strategyId })}`),
  executionLatency: () => get<ExecutionLatencySummary>("/api/v1/orders/execution-latency"),

  shadowModeStatus: () => get<ShadowModeStatus>("/api/v1/shadow-mode/status"),

  goLiveReadiness: (strategyId: string) =>
    get<GoLiveReadiness>(`/api/v1/go-live/readiness/${strategyId}`),

  currentRiskLimit: () => get<CurrentRiskLimit | null>("/api/v1/risk-limits/current"),
  riskLimitChangeRequests: (status?: string) =>
    get<RiskLimitChangeRequest[]>(`/api/v1/risk-limits/change-requests${toQuery({ status })}`),
  stageRiskLimitChange: (payload: RiskLimitChangePayload) =>
    post<RiskLimitChangeRequest>("/api/v1/risk-limits/change-requests", payload),
  confirmRiskLimitChange: (requestId: string) =>
    post<RiskLimitChangeRequest>(`/api/v1/risk-limits/change-requests/${requestId}/confirm`),
  rejectRiskLimitChange: (requestId: string, reason: string) =>
    post<RiskLimitChangeRequest>(`/api/v1/risk-limits/change-requests/${requestId}/reject`, {
      reason,
    }),

  writeBrokerCredentials: (broker: BrokerId, credentials: Record<string, string>) =>
    postNoContent(`/api/v1/broker/credentials/${broker}`, { credentials }),
  deleteBrokerCredentials: (broker: BrokerId) => del(`/api/v1/broker/credentials/${broker}`),

  writeLlmProviderKey: (provider: LlmProviderId, apiKey: string) =>
    postNoContent(`/api/v1/settings/llm-provider-keys/${provider}`, { api_key: apiKey }),
  deleteLlmProviderKey: (provider: LlmProviderId) =>
    del(`/api/v1/settings/llm-provider-keys/${provider}`),
};
