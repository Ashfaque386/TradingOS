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

// REL-038: build_broker() resolves ONE adapter (Zerodha-primary/Upstox-fallback) -- a real,
// separately-funded Upstox account never shows up there as long as the Zerodha call itself
// succeeds, even with a genuinely empty account. These match
// src/api/routers/portfolio.py::BrokerMarginEntry/BrokerPositionsEntry, which query each real
// broker independently so both real accounts are shown, never silently shadowed by one another.
export interface BrokerMarginEntry {
  broker: string;
  configured: boolean;
  margin: Margin | null;
  error: string | null;
}

export interface BrokerPositionsEntry {
  broker: string;
  configured: boolean;
  positions: Position[];
  error: string | null;
}

// REL-036: matches src/api/routers/broker_config.py::BrokerStatusResponse -- whether
// build_broker() can real-construct an adapter right now, the same resolution every Live
// portfolio/positions/margin endpoint depends on. Named distinctly from the existing
// `BrokerStatus` below (settings.py's IntegrationsStatus row, which only checks whether a
// credential string is present) -- TypeScript would otherwise silently merge the two same-named
// interfaces via declaration merging instead of erroring, which is not what either one means.
export interface LiveBrokerStatus {
  configured: boolean;
  broker_name: string | null;
  detail: string | null;
}

// REL-036: matches src/brokers/base.py::OrderResponse -- the real, read-only order book from
// whichever broker is configured (never a locally-placed order; BrokerAdapter has no
// place/modify/cancel method anywhere in this codebase, Business Rule 3).
export interface BrokerOrder {
  broker_order_id: string;
  status: string;
  symbol: string;
  side: "BUY" | "SELL";
  order_type: string;
  quantity: number;
  filled_quantity: number;
  average_price: number | null;
  limit_price: number | null;
  rejection_reason: string | null;
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

// REL-068 -- real per-agent execution stats over the AgentRun ledger (src/agents/analytics.py),
// every root graph run AND every per-node child run, not just the root-only rows `runs()`
// returns. `success_rate`/duration fields are `null`, never fabricated, when there isn't enough
// real data yet for that figure (no finished run, or no completed run with a real ended_at).
export interface AgentAnalyticsSummaryRow {
  agent_name: string;
  display_name: string;
  total_runs: number;
  completed: number;
  failed: number;
  running: number;
  success_rate: number | null;
  avg_duration_seconds: number | null;
  p50_duration_seconds: number | null;
  p95_duration_seconds: number | null;
}

export interface AgentAnalyticsTrendPoint {
  date: string;
  total_runs: number;
  completed: number;
  failed: number;
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
  // REL-040: real count of this strategy's own backtest_results rows, so the picker can show
  // which strategies actually have history worth opening.
  backtest_count: number;
  // REL-044: real, previously-unserialized columns. max_drawdown_limit has always existed on
  // Strategy; the rest are the Strategy Generator Agent's StrategyLogic fields beyond
  // hypothesis, computed by the LLM on every run but only ever partially persisted until this
  // release -- null for a strategy generated before this migration, honestly, not backfilled.
  // research_context/market_context are the CEO/Market Analyst Agents' own real
  // ResearchDirective/MarketContext that led to this strategy being proposed.
  max_drawdown_limit: number | null;
  entry_conditions: string | null;
  exit_conditions: string | null;
  stop_loss: string | null;
  take_profit: string | null;
  position_sizing: string | null;
  confidence_score: number | null;
  research_context: Record<string, unknown> | null;
  market_context: Record<string, unknown> | null;
  // REL-044: the current version's own validation_status, for the Kanban card's status dot.
  current_version_validation_status: string | null;
}

export interface StrategyVersionSummary {
  id: string;
  version_no: number;
  validation_status: string;
  validator_feedback: string | null;
  // REL-044: real columns on StrategyVersion (option_legs/option_expiry real since REL-035,
  // option_rationale new this release) -- null for an Equity strategy, or an F&O one whose
  // options grounding degraded.
  option_legs: { symbol: string; option_type: string; strike: number; side: string; quantity: number }[] | null;
  option_expiry: string | null;
  option_rationale: string | null;
}

// REL-048: a human-submitted suggestion against a real strategy, reviewed by a lightweight LLM
// step and -- if judged sound -- implemented by re-entering the real agent pipeline, producing a
// genuine new StrategyVersion + BacktestResult (`resulting_version_id`) rather than a field edit.
export interface StrategySuggestion {
  id: string;
  strategy_id: string;
  submitted_by_user_id: string;
  suggestion_text: string;
  status: "Pending" | "Reviewing" | "Rejected" | "Applied";
  ai_verdict: string | null;
  ai_reasoning: string | null;
  resulting_version_id: string | null;
  created_at: string;
  reviewed_at: string | null;
}

export interface SuggestionReviewTriggerResponse {
  job_id: string;
  status: string;
}

export interface SuggestionReviewJobStatus {
  job_id: string;
  status: "Running" | "Completed";
  suggestion: StrategySuggestion | null;
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
  // Real column, always set -- the actual starting capital this run used.
  initial_capital: number;
  has_equity_curve: boolean;
  // REL-017 E17.4 (DB-007): real column. UPDATE 2026-08-05 (REL-023): a real Monte Carlo
  // simulation now runs against real per-trade returns (REL-022) for every newly-triggered
  // backtest -- still null for backtests created before this release (not backfilled) or with
  // fewer than 2 usable returns either way, exposed honestly rather than hidden.
  monte_carlo_p95_max_drawdown: number | null;
  // REL-072: real provenance -- whether the real split/bonus adjustment pipeline
  // (src/engine/backtest/corporate_actions_adjust.py) was applied to this backtest's OHLCV
  // data. `null` for a backtest run before this release (genuinely never adjusted).
  data_adjusted: boolean | null;
  // REL-073: real reproducibility provenance -- which provider's data this backtest actually
  // ran against, and when that data was last fetched. Both `null` when unknown (never guessed).
  provider_used: string | null;
  data_retrieved_at: string | null;
  created_at: string;
  // REL-040: the real Evaluator/Optimization/RiskManager/Deployment agent-pipeline outcome for
  // this backtest run (src/api/routers/agents.py::_persist_strategy_progress) -- previously
  // computed and persisted but never returned by any endpoint. "Not yet evaluated" (null) is a
  // real, honest state for a backtest the agent pipeline hasn't reached yet, not an error.
  evaluation_verdict: string | null;
  evaluation_failure_reasons: string[] | null;
  optimization_best_params: Record<string, number> | null;
  optimization_robustness_score: number | null;
  risk_assessment_passed: boolean | null;
  risk_assessment_notes: string | null;
  deployment_recommendation: string | null;
  deployment_rationale: string | null;
}

export interface StrategyDetail extends StrategySummary {
  versions: StrategyVersionSummary[];
  backtests: BacktestSummary[];
}

// REL-040: GET /strategies/backtests/latest and /strategies/backtests/compare tag each row with
// which strategy it belongs to, since both endpoints span every strategy rather than one.
export interface BacktestWithStrategy extends BacktestSummary {
  strategy_id: string;
  strategy_name: string;
}

export interface BacktestCompareRow extends BacktestWithStrategy {
  equity_curve: EquityCurvePoint[];
}

export interface MonteCarloHistogramResponse {
  bucket_edges: number[];
  bucket_counts: number[];
  percentile_50_max_drawdown: number;
  percentile_75_max_drawdown: number;
  percentile_90_max_drawdown: number;
  percentile_95_max_drawdown: number;
  percentile_99_max_drawdown: number;
  historical_max_drawdown: number;
  n_simulations: number;
}

// REL-069: real pairwise return correlation between compared runs -- a `null` cell means too
// few real overlapping calendar days between that pair's equity curves, never a fabricated 0.
export interface CorrelationMatrixResponse {
  run_ids: string[];
  run_labels: string[];
  matrix: (number | null)[][];
}

export interface VersionCode {
  version_no: number;
  python_code: string;
}

// All fields optional -- omitted ones fall back to the backend's existing lake-latest-date/
// 365-day-lookback/default-capital behavior.
export interface BacktestTriggerRequest {
  date_from?: string;
  date_to?: string;
  initial_capital?: number;
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

/** FastAPI's own real error shape is always `{"detail": "..."}` -- extracts that plain message
 * when the body parses as JSON with one, so a caller-surfaced error reads as the real reason
 * (e.g. "No historical data ingested for NIFTY 50") instead of a raw JSON blob. Falls back to
 * today's raw-text format for anything that isn't shaped that way (a 500 with an HTML error
 * page, a non-JSON body, etc.) rather than fabricating a message. */
async function extractErrorMessage(method: string, path: string, res: Response): Promise<string> {
  const text = await res.text();
  try {
    const parsed = JSON.parse(text) as { detail?: unknown };
    if (typeof parsed.detail === "string") return parsed.detail;
  } catch {
    // Not JSON -- fall through to the raw-text format below.
  }
  return `${method} ${path} failed: ${res.status} ${text}`;
}

/** Carries the real HTTP status alongside the message extractErrorMessage() produces -- that
 * message is now the server's plain `detail` text (e.g. "Incorrect email or password"), which
 * no longer contains the old raw `failed: 401` substring login/page.tsx's isAuthRejection() used
 * to regex-match. Callers that need to distinguish "a real 4xx rejection" from "the request
 * never reached the server" should check `status`, not parse `message`. */
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    throw new ApiError(res.status, await extractErrorMessage("POST", path, res));
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

// REL-067 -- real, date-aligned technical indicators (src/data/features/indicators.py, wired to
// GET /market/ohlcv/{symbol}/indicators for the first time this release). A rolling-window field
// is genuinely `null` for the leading bars that don't have enough history yet -- never a
// fabricated 0 or a copy of the close price standing in for a real value.
export interface IndicatorPoint {
  date: string;
  close: number;
  sma_20: number | null;
  ema_20: number | null;
  rsi_14: number | null;
  atr_14: number | null;
  bb_upper: number | null;
  bb_mid: number | null;
  bb_lower: number | null;
  macd_line: number | null;
  macd_signal: number | null;
  macd_histogram: number | null;
}

// REL-067 -- real India VIX + NSE sector-index day-change (src/data/market_pulse.py), the same
// real data the Market Analyst Agent's own IndiaVixSkill/NseSectorDataSkill already fetch, now
// also exposed here. `india_vix` is `null` and `sectors` can be shorter than 4 if yfinance had
// no data for one or more tickers at request time -- honestly omitted, never fabricated.
export interface MarketPulseIndex {
  name: string;
  value: number;
  change_pct: number;
  as_of: string;
}

export interface MarketPulseResponse {
  india_vix: MarketPulseIndex | null;
  sectors: MarketPulseIndex[];
}

// REL-010 E10.8a -- real per-symbol ingestion freshness (src/data/datalake/freshness.py), the
// exact same check the Scheduler's own pre-research-cycle gate already enforces. Existed on the
// backend since REL-010; this is its first frontend consumer (REL-067).
export interface SymbolFreshness {
  symbol: string;
  is_fresh: boolean;
  expected_date: string;
  latest_available: string | null;
}

export interface DatalakeStatusResponse {
  status: "Fresh" | "Stale";
  as_of: string;
  total_symbols: number;
  stale_symbols: SymbolFreshness[];
}

// REL-071: src/data/ingest/instrument_sync.py's real, locally-synced Upstox instrument master
// (src/models/instrument.py) -- unlike `symbols` above (whatever's already been ingested into
// the EOD lake), this is the full real, searchable NSE/BSE equity + index universe.
export interface InstrumentSummary {
  instrument_key: string;
  exchange: string;
  segment: string;
  symbol: string;
  name: string;
  instrument_type: string;
  isin: string | null;
}

export interface InstrumentSearchResponse {
  items: InstrumentSummary[];
  total: number;
  page: number;
  page_size: number;
}

// REL-073: src/api/routers/market_data.py's GET /market/providers/status -- a config-only
// check (no live network call), same shape/spirit as the existing broker /status endpoint.
export interface ProviderStatus {
  name: string;
  configured: boolean;
  detail: string | null;
}

export interface ProviderStatusResponse {
  providers: ProviderStatus[];
  active_provider: string;
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
  marginByBroker: () => get<BrokerMarginEntry[]>("/api/v1/portfolio/margin/by-broker"),
  positionsByBroker: () => get<BrokerPositionsEntry[]>("/api/v1/positions/by-broker"),
  pnl: () => get<PnLResponse>("/api/v1/portfolio/pnl"),
  riskMetrics: () => get<RiskMetricsResponse>("/api/v1/portfolio/risk-metrics"),
  allocation: () => get<AllocationResponse>("/api/v1/portfolio/allocation"),
  brokerStatus: () => get<LiveBrokerStatus>("/api/v1/broker/status"),
  brokerOrderBook: () => get<BrokerOrder[]>("/api/v1/broker/order-book"),
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
  agentAnalyticsSummary: (days: number) =>
    get<AgentAnalyticsSummaryRow[]>(`/api/v1/agents/analytics/summary?days=${days}`),
  agentAnalyticsTrend: (days: number) =>
    get<AgentAnalyticsTrendPoint[]>(`/api/v1/agents/analytics/trend?days=${days}`),
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
  triggerBacktest: (id: string, config?: BacktestTriggerRequest) =>
    post<BacktestTriggerResponse>(`/api/v1/strategies/${id}/backtest`, config),
  backtestJobStatus: (jobId: string) =>
    get<BacktestJobStatus>(`/api/v1/strategies/backtests/jobs/${jobId}/status`),
  equityCurve: (backtestId: string) =>
    get<EquityCurvePoint[]>(`/api/v1/strategies/backtests/${backtestId}/equity-curve`),
  backtestTrades: (backtestId: string) =>
    get<TradeSummary[]>(`/api/v1/strategies/backtests/${backtestId}/trades`),
  backtestWalkForward: (backtestId: string) =>
    get<WalkForwardWindow[]>(`/api/v1/strategies/backtests/${backtestId}/walk-forward`),
  // REL-040: cross-strategy views, previously assembled client-side with an N+1 fetch per
  // strategy -- now one real server-side query each.
  latestBacktests: () => get<BacktestWithStrategy[]>("/api/v1/strategies/backtests/latest"),
  compareBacktests: (ids: string[]) =>
    get<BacktestCompareRow[]>(`/api/v1/strategies/backtests/compare${toQuery({ ids: ids.join(",") })}`),
  compareBacktestsCorrelation: (ids: string[]) =>
    get<CorrelationMatrixResponse>(
      `/api/v1/strategies/backtests/compare/correlation${toQuery({ ids: ids.join(",") })}`,
    ),
  monteCarloHistogram: (backtestId: string) =>
    get<MonteCarloHistogramResponse>(`/api/v1/strategies/backtests/${backtestId}/monte-carlo`),
  backtestExportPath: (backtestId: string, format: "csv" | "ndjson") =>
    `/api/v1/strategies/backtests/${backtestId}/export${toQuery({ format })}`,
  promoteStrategy: (id: string, toStatus: StrategyStatus) =>
    post<StrategySummary>(`/api/v1/strategies/${id}/promote`, { to_status: toStatus }),

  // REL-048/049: suggest a change to a strategy; any authenticated user can submit, SA/PM/RM can
  // trigger the AI review that -- if the suggestion is judged sound -- re-enters the real agent
  // pipeline and produces a genuine new StrategyVersion + BacktestResult.
  listSuggestions: (strategyId: string) =>
    get<StrategySuggestion[]>(`/api/v1/strategies/${strategyId}/suggestions`),
  submitSuggestion: (strategyId: string, text: string) =>
    post<StrategySuggestion>(`/api/v1/strategies/${strategyId}/suggestions`, { text }),
  reviewSuggestion: (strategyId: string, suggestionId: string) =>
    post<SuggestionReviewTriggerResponse>(
      `/api/v1/strategies/${strategyId}/suggestions/${suggestionId}/review`,
    ),
  suggestionReviewJobStatus: (jobId: string) =>
    get<SuggestionReviewJobStatus>(`/api/v1/strategies/suggestions/jobs/${jobId}/status`),

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
  ohlcvIndicators: (symbol: string) =>
    get<IndicatorPoint[]>(`/api/v1/market/ohlcv/${encodeURIComponent(symbol)}/indicators`),
  symbols: () => get<string[]>("/api/v1/market/symbols"),
  marketPulse: () => get<MarketPulseResponse>("/api/v1/market/pulse"),
  datalakeStatus: () => get<DatalakeStatusResponse>("/api/v1/market/datalake/status"),
  instrumentSearch: (params: {
    q?: string;
    exchange?: string;
    instrument_type?: string;
    page?: number;
    page_size?: number;
  }) => get<InstrumentSearchResponse>(`/api/v1/market/instruments/search${toQuery(params)}`),
  providerStatus: () => get<ProviderStatusResponse>("/api/v1/market/providers/status"),

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
