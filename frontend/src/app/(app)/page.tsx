"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { formatCompactINR } from "@/lib/utils";
import { usePortfolioSocket } from "@/hooks/usePortfolioSocket";
import { usePageStatus } from "@/hooks/usePageStatus";
import { useAccountScopeStore } from "@/lib/account-scope-store";
import { Card } from "@/components/ui/card";
import { NumberTicker } from "@/components/ui/number-ticker";
import { RiskGauge } from "@/components/portfolio/risk-gauge";
import { ExposureDonut } from "@/components/portfolio/exposure-donut";
import { KillSwitchButton } from "@/components/portfolio/kill-switch-button";
import { CandlestickChart } from "@/components/portfolio/candlestick-chart";
import { AccountsPanel } from "@/components/portfolio/accounts-panel";
import {
  BrokerConnectionBanner,
  type BrokerConnectionState,
} from "@/components/portfolio/broker-connection-banner";

/** Phase 2C: fixed premium layout replacing the drag/resize GridWorkspace grid -- a persistent
 * Kill Switch band, a hero P&L row, a risk-gauge row, an allocation donut, a unified tabbed
 * Accounts panel, and the candlestick chart full-width at the bottom, instead of manually
 * positioned, user-draggable panels.
 *
 * REL-066: the Kill Switch is a real-money safety control, not account display data, so it
 * renders as its own full-width band at the very top of the page, unconditional on account
 * scope -- it halts every connected broker regardless of which account you're currently viewing.
 * The Live aggregate hero/gauges/donut below (real broker data via build_broker(), Zerodha-
 * primary/Upstox-fallback) and the per-account Paper/Zerodha/Upstox breakdown (AccountsPanel)
 * are two different things: the former is genuine cross-account aggregate risk, the latter is
 * each account's own real figures, tabbed rather than stacked as 3 near-identical sections.
 * Paper's simulated capital and a Live broker's real margin are still never summed into one
 * blended number -- see AccountsPanel's own note. The candlestick chart stays visible regardless
 * of scope: it's market data, not account data. */
export default function PortfolioCommandCenter() {
  const { tick, connected } = usePortfolioSocket();
  const scope = useAccountScopeStore((s) => s.scope);

  usePageStatus("Portfolio & Risk Command Center", connected);

  const positionsQuery = useQuery({ queryKey: ["positions"], queryFn: api.positions });
  const marginQuery = useQuery({ queryKey: ["margin"], queryFn: api.margin });
  const pnlQuery = useQuery({ queryKey: ["pnl"], queryFn: api.pnl });
  const riskQuery = useQuery({ queryKey: ["risk-metrics"], queryFn: api.riskMetrics });
  const allocationQuery = useQuery({ queryKey: ["allocation"], queryFn: api.allocation });
  const brokerStatusQuery = useQuery({ queryKey: ["broker-status"], queryFn: api.brokerStatus });
  const marginByBrokerQuery = useQuery({
    queryKey: ["margin-by-broker"],
    queryFn: api.marginByBroker,
  });
  const positionsByBrokerQuery = useQuery({
    queryKey: ["positions-by-broker"],
    queryFn: api.positionsByBroker,
  });

  const summaryQuery = useQuery({
    queryKey: ["account-summary"],
    queryFn: () => api.accountSummary(),
    enabled: scope !== "live",
    refetchInterval: 15_000,
  });
  const paperPositionsQuery = useQuery({
    queryKey: ["paper-positions"],
    queryFn: () => api.paperPositions(),
    enabled: scope !== "live",
    refetchInterval: 15_000,
  });

  const livePnl = tick?.pnl ?? pnlQuery.data?.total_pnl ?? 0;
  const positive = livePnl >= 0;
  const dailyLimit = riskQuery.data?.daily_loss_limit ?? pnlQuery.data?.daily_loss_limit ?? null;
  const pctOfLimit = riskQuery.data?.pct_of_daily_limit_used ?? tick?.drawdown ?? null;

  const liveQueryErrored =
    positionsQuery.isError ||
    marginQuery.isError ||
    pnlQuery.isError ||
    riskQuery.isError ||
    allocationQuery.isError;
  const brokerState: BrokerConnectionState =
    brokerStatusQuery.data?.configured === false
      ? "not_configured"
      : liveQueryErrored
        ? "error"
        : "ok";
  const brokerErrorDetail =
    (marginQuery.error as Error | null)?.message ??
    (positionsQuery.error as Error | null)?.message ??
    null;

  const showLive = scope !== "paper";
  const showPaper = scope !== "live";
  const summary = summaryQuery.data;

  return (
    <main className="mx-auto flex w-full max-w-[1440px] flex-1 flex-col gap-4 p-6 sm:p-8">
      <KillSwitchButton />

      {showLive && (
        <section className="flex flex-col gap-4">
          {scope === "both" && (
            <p className="text-[10px] font-medium uppercase tracking-[0.18em] text-text-faint">
              Live Account
            </p>
          )}
          {brokerState !== "ok" && (
            <BrokerConnectionBanner state={brokerState} detail={brokerErrorDetail} />
          )}

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
            <Card eyebrow="Live" title="Total P&L" className="lg:col-span-12">
              <div className="flex flex-wrap items-end justify-between gap-6">
                <div>
                  <NumberTicker
                    value={livePnl}
                    format={formatCompactINR}
                    className={`font-mono-tabular text-5xl font-semibold tracking-tight ${
                      positive ? "text-up" : "text-down"
                    }`}
                  />
                  <p className="mt-2 text-xs text-text-faint">
                    Unrealized {formatCompactINR(pnlQuery.data?.unrealized_pnl ?? 0)} · Realized{" "}
                    {formatCompactINR(pnlQuery.data?.realized_pnl ?? 0)}
                  </p>
                </div>
                <div className="min-w-[180px] flex-1 sm:max-w-[260px]">
                  <div className="mb-1 flex items-baseline justify-between text-[11px] text-text-faint">
                    <span>Daily stop-loss</span>
                    <span>{pctOfLimit !== null ? `${pctOfLimit.toFixed(0)}%` : "—"}</span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-bg">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-warn to-down transition-all duration-700"
                      style={{ width: `${Math.min(pctOfLimit ?? 0, 100)}%` }}
                    />
                  </div>
                  <p className="mt-1 text-[11px] text-text-faint">
                    {dailyLimit !== null
                      ? `Limit ${formatCompactINR(dailyLimit)}`
                      : "No Risk Manager limit configured yet"}
                  </p>
                </div>
              </div>
            </Card>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Card eyebrow="Backtested" title="Sharpe Ratio">
              <RiskGauge
                label="Sharpe"
                value={riskQuery.data?.sharpe_ratio ?? null}
                min={-1}
                max={3}
                displayValue={riskQuery.data?.sharpe_ratio?.toFixed(2) ?? ""}
                unavailableReason="No live strategies deployed"
                colorVar="var(--color-brand-via)"
                subtext="Capital-weighted, live strategies"
              />
            </Card>

            <Card eyebrow="Risk" title="Daily P&L vs Limit">
              <RiskGauge
                label="Of daily limit"
                value={pctOfLimit}
                min={0}
                max={100}
                displayValue={pctOfLimit !== null ? `${pctOfLimit.toFixed(0)}%` : ""}
                unavailableReason="No stop-loss limit set"
                colorVar={(pctOfLimit ?? 0) > 70 ? "var(--color-down)" : "var(--color-up)"}
                subtext="Share of max daily loss used"
              />
            </Card>

            <Card eyebrow="vs Nifty 50" title="Portfolio Beta">
              <RiskGauge
                label="Beta"
                value={riskQuery.data?.beta_vs_nifty50 ?? null}
                min={0}
                max={2}
                displayValue={riskQuery.data?.beta_vs_nifty50?.toFixed(2) ?? ""}
                unavailableReason="No live equity-curve tracker yet"
                colorVar="var(--color-brand-to)"
              />
            </Card>
          </div>

          <Card eyebrow="Allocation" title="Live Exposure">
            <ExposureDonut
              bySymbol={allocationQuery.data?.by_symbol ?? []}
              grossExposure={allocationQuery.data?.gross_exposure ?? 0}
              sectorAvailable={allocationQuery.data?.sector_data_available ?? false}
              strategyAvailable={allocationQuery.data?.strategy_data_available ?? false}
            />
          </Card>
        </section>
      )}

      <AccountsPanel
        showPaper={showPaper}
        showLive={showLive}
        paperSummary={summary}
        paperSummaryLoading={summaryQuery.isLoading}
        paperPositions={paperPositionsQuery.data}
        paperPositionsLoading={paperPositionsQuery.isLoading}
        brokerMargins={marginByBrokerQuery.data ?? []}
        brokerPositions={positionsByBrokerQuery.data ?? []}
      />

      <Card eyebrow="Market" title="Candlestick Chart">
        <CandlestickChart />
      </Card>
    </main>
  );
}
