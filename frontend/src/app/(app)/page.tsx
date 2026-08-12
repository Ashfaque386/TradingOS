"use client";

import Link from "next/link";
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
import { PositionsTable } from "@/components/portfolio/positions-table";
import { MarginPanel } from "@/components/portfolio/margin-panel";
import { CapitalSummary } from "@/components/portfolio/capital-summary";
import { KillSwitchButton } from "@/components/portfolio/kill-switch-button";
import { CandlestickChart } from "@/components/portfolio/candlestick-chart";
import {
  BrokerConnectionBanner,
  type BrokerConnectionState,
} from "@/components/portfolio/broker-connection-banner";
import { PaperPositionsTable } from "@/components/paper-trading/paper-positions-table";

/** Phase 2C: fixed premium layout replacing the drag/resize GridWorkspace grid -- a hero row
 * (P&L + Kill Switch), a risk-gauge row, a secondary allocation/margin/positions row, and the
 * candlestick chart full-width at the bottom, instead of manually positioned, user-draggable
 * panels.
 *
 * REL-036: scope-aware -- the Live section below is real broker data (build_broker(), Zerodha/
 * Upstox) and the Paper section is the real seeded ₹100,000 account (same data /account shows).
 * They are never summed into one figure -- a Paper account's simulated capital and a Live
 * broker's real margin are not the same unit of risk -- so "Both" renders them as two separate,
 * clearly tagged blocks, not one blended number. KillSwitchButton and the candlestick chart stay
 * visible regardless of scope: the kill switch is a real-money safety control, not account
 * display data, and the chart is market data, not account data. */
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
  const realizedPositive = (summary?.realized_pnl_total ?? 0) >= 0;
  const unrealizedPositive = (summary?.unrealized_pnl_total ?? 0) >= 0;

  return (
    <main className="mx-auto flex w-full max-w-[1440px] flex-1 flex-col gap-4 p-6 sm:p-8">
      <div className="flex justify-end">
        <div className="w-full sm:max-w-sm">
          <KillSwitchButton />
        </div>
      </div>

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

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
            <Card eyebrow="Allocation" title="Live Exposure" className="lg:col-span-5">
              <ExposureDonut
                bySymbol={allocationQuery.data?.by_symbol ?? []}
                grossExposure={allocationQuery.data?.gross_exposure ?? 0}
                sectorAvailable={allocationQuery.data?.sector_data_available ?? false}
                strategyAvailable={allocationQuery.data?.strategy_data_available ?? false}
              />
            </Card>

            <Card eyebrow="Broker" title="Margin" className="lg:col-span-3">
              <MarginPanel margin={marginQuery.data} state={brokerState} />
            </Card>

            <Card eyebrow="Open" title="Positions" className="lg:col-span-4">
              <PositionsTable positions={positionsQuery.data ?? []} />
            </Card>
          </div>
        </section>
      )}

      {showPaper && (
        <section className="flex flex-col gap-4">
          {scope === "both" && (
            <p className="text-[10px] font-medium uppercase tracking-[0.18em] text-text-faint">
              Paper Account
            </p>
          )}

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
            <Card
              eyebrow="Paper"
              title="Account Equity"
              className="lg:col-span-12"
              action={
                <Link
                  href="/account"
                  className="text-[11px] font-medium text-text-dim underline underline-offset-2 hover:text-text"
                >
                  Full ledger →
                </Link>
              }
            >
              {summaryQuery.isLoading ? (
                <div className="h-16 animate-pulse rounded-xl bg-bg" />
              ) : (
                <div className="grid grid-cols-2 gap-6 sm:grid-cols-4">
                  <div>
                    <p className="text-[10px] uppercase tracking-[0.18em] text-text-faint">
                      Equity
                    </p>
                    <NumberTicker
                      value={summary?.equity ?? 0}
                      format={formatCompactINR}
                      className="font-mono-tabular text-2xl font-semibold tracking-tight text-text"
                    />
                  </div>
                  <div>
                    <p className="text-[10px] uppercase tracking-[0.18em] text-text-faint">
                      Cash
                    </p>
                    <p className="font-mono-tabular text-2xl font-semibold tracking-tight text-text-dim">
                      {formatCompactINR(summary?.cash ?? 0)}
                    </p>
                  </div>
                  <div>
                    <p className="text-[10px] uppercase tracking-[0.18em] text-text-faint">
                      Realized
                    </p>
                    <p
                      className={`font-mono-tabular text-2xl font-semibold tracking-tight ${
                        realizedPositive ? "text-up" : "text-down"
                      }`}
                    >
                      {formatCompactINR(summary?.realized_pnl_total ?? 0)}
                    </p>
                  </div>
                  <div>
                    <p className="text-[10px] uppercase tracking-[0.18em] text-text-faint">
                      Unrealized
                    </p>
                    <p
                      className={`font-mono-tabular text-2xl font-semibold tracking-tight ${
                        unrealizedPositive ? "text-up" : "text-down"
                      }`}
                    >
                      {formatCompactINR(summary?.unrealized_pnl_total ?? 0)}
                    </p>
                  </div>
                </div>
              )}
            </Card>
          </div>

          <Card eyebrow="Paper" title="Capital">
            {summaryQuery.isLoading ? (
              <div className="h-16 animate-pulse rounded-xl bg-bg" />
            ) : (
              <CapitalSummary
                used={summary?.margin_blocked ?? 0}
                available={(summary?.cash ?? 0) - (summary?.margin_blocked ?? 0)}
              />
            )}
          </Card>

          <Card eyebrow="Open" title="Paper Positions">
            {paperPositionsQuery.isLoading ? (
              <div className="h-40 animate-pulse rounded-xl bg-bg" />
            ) : (
              <PaperPositionsTable positions={paperPositionsQuery.data ?? []} />
            )}
          </Card>
        </section>
      )}

      <Card eyebrow="Market" title="Candlestick Chart">
        <CandlestickChart />
      </Card>
    </main>
  );
}
