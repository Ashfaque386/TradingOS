const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8001";

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

export const ALERT_LEVELS = [
  "critical_errors",
  "executed_trades",
  "risk_warnings",
  "strategy_promotions",
] as const;
export type AlertLevel = (typeof ALERT_LEVELS)[number];

export type ChannelType = "Telegram" | "Discord" | "WhatsApp" | "Slack" | "Email";

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

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store", headers: authHeaders() });
  if (!res.ok) {
    throw new Error(`GET ${path} failed: ${res.status} ${await res.text()}`);
  }
  return res.json() as Promise<T>;
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

export interface LoginResponse {
  access_token: string;
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

export const api = {
  login: (email: string, password: string) =>
    post<LoginResponse>("/api/v1/auth/login", { email, password }),
  me: () => get<CurrentUser>("/api/v1/auth/me"),

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
};
