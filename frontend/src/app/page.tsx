"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { formatCompactINR } from "@/lib/utils";
import { usePortfolioSocket } from "@/hooks/usePortfolioSocket";
import { RequireAuth } from "@/lib/auth";
import { TopBar } from "@/components/layout/top-bar";
import { GlassCard } from "@/components/ui/glass-card";
import { NumberTicker } from "@/components/ui/number-ticker";
import { RiskGauge } from "@/components/portfolio/risk-gauge";
import { ExposureDonut } from "@/components/portfolio/exposure-donut";
import { PositionsTable } from "@/components/portfolio/positions-table";
import { MarginPanel } from "@/components/portfolio/margin-panel";
import { KillSwitchButton } from "@/components/portfolio/kill-switch-button";

export default function PortfolioCommandCenter() {
  const { tick, connected } = usePortfolioSocket();

  const positionsQuery = useQuery({ queryKey: ["positions"], queryFn: api.positions });
  const marginQuery = useQuery({ queryKey: ["margin"], queryFn: api.margin });
  const pnlQuery = useQuery({ queryKey: ["pnl"], queryFn: api.pnl });
  const riskQuery = useQuery({ queryKey: ["risk-metrics"], queryFn: api.riskMetrics });
  const allocationQuery = useQuery({ queryKey: ["allocation"], queryFn: api.allocation });

  const livePnl = tick?.pnl ?? pnlQuery.data?.total_pnl ?? 0;
  const positive = livePnl >= 0;
  const dailyLimit = riskQuery.data?.daily_loss_limit ?? pnlQuery.data?.daily_loss_limit ?? null;
  const pctOfLimit = riskQuery.data?.pct_of_daily_limit_used ?? tick?.drawdown ?? null;

  return (
    <RequireAuth>
      <TopBar connected={connected} subtitle="Portfolio & Risk Command Center" />

      <main className="mx-auto flex w-full max-w-[1440px] flex-1 flex-col gap-4 p-6 sm:p-8">
        {/* Hero row: live PnL + Kill Switch */}
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
          <GlassCard eyebrow="Live" title="Total P&L" className="xl:col-span-8">
            <div className="flex flex-wrap items-end justify-between gap-6">
              <div>
                <NumberTicker
                  value={livePnl}
                  format={formatCompactINR}
                  className={`font-mono-tabular text-5xl font-semibold tracking-tight ${
                    positive ? "text-emerald-400" : "text-rose-400"
                  }`}
                />
                <p className="mt-2 text-xs text-zinc-500">
                  Unrealized {formatCompactINR(pnlQuery.data?.unrealized_pnl ?? 0)} · Realized{" "}
                  {formatCompactINR(pnlQuery.data?.realized_pnl ?? 0)}
                </p>
              </div>
              <div className="min-w-[180px] flex-1 sm:max-w-[260px]">
                <div className="mb-1 flex items-baseline justify-between text-[11px] text-zinc-500">
                  <span>Daily stop-loss</span>
                  <span>{pctOfLimit !== null ? `${pctOfLimit.toFixed(0)}%` : "—"}</span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-white/5">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-amber-400 to-rose-500 transition-all duration-700"
                    style={{ width: `${Math.min(pctOfLimit ?? 0, 100)}%` }}
                  />
                </div>
                <p className="mt-1 text-[11px] text-zinc-600">
                  {dailyLimit !== null
                    ? `Limit ${formatCompactINR(dailyLimit)}`
                    : "No Risk Manager limit configured yet"}
                </p>
              </div>
            </div>
          </GlassCard>

          <div className="xl:col-span-4">
            <KillSwitchButton />
          </div>
        </div>

        {/* Risk gauges */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <GlassCard eyebrow="Backtested" title="Sharpe Ratio">
            <RiskGauge
              label="Sharpe"
              value={riskQuery.data?.sharpe_ratio ?? null}
              min={-1}
              max={3}
              displayValue={riskQuery.data?.sharpe_ratio?.toFixed(2) ?? ""}
              unavailableReason="No live strategies deployed"
              colorVar="var(--accent-cyan)"
              subtext="Capital-weighted, live strategies"
            />
          </GlassCard>

          <GlassCard eyebrow="Risk" title="Daily P&L vs Limit">
            <RiskGauge
              label="Of daily limit"
              value={pctOfLimit}
              min={0}
              max={100}
              displayValue={pctOfLimit !== null ? `${pctOfLimit.toFixed(0)}%` : ""}
              unavailableReason="No stop-loss limit set"
              colorVar={(pctOfLimit ?? 0) > 70 ? "var(--accent-crimson)" : "var(--accent-emerald)"}
              subtext="Share of max daily loss used"
            />
          </GlassCard>

          <GlassCard eyebrow="vs Nifty 50" title="Portfolio Beta">
            <RiskGauge
              label="Beta"
              value={riskQuery.data?.beta_vs_nifty50 ?? null}
              min={0}
              max={2}
              displayValue={riskQuery.data?.beta_vs_nifty50?.toFixed(2) ?? ""}
              unavailableReason="No live equity-curve tracker yet"
              colorVar="var(--accent-purple)"
            />
          </GlassCard>
        </div>

        {/* Exposure + Margin + Positions */}
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
          <GlassCard eyebrow="Allocation" title="Live Exposure" className="xl:col-span-5">
            <ExposureDonut
              bySymbol={allocationQuery.data?.by_symbol ?? []}
              grossExposure={allocationQuery.data?.gross_exposure ?? 0}
              sectorAvailable={allocationQuery.data?.sector_data_available ?? false}
              strategyAvailable={allocationQuery.data?.strategy_data_available ?? false}
            />
          </GlassCard>

          <GlassCard eyebrow="Broker" title="Margin" className="xl:col-span-3">
            <MarginPanel margin={marginQuery.data} />
          </GlassCard>

          <GlassCard eyebrow="Open" title="Positions" className="xl:col-span-4">
            <PositionsTable positions={positionsQuery.data ?? []} />
          </GlassCard>
        </div>
      </main>
    </RequireAuth>
  );
}
