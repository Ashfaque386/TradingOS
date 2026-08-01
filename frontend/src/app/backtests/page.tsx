"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api } from "@/lib/api";
import { RequireAuth } from "@/lib/auth";
import { TopBar } from "@/components/layout/top-bar";
import { GlassCard } from "@/components/ui/glass-card";
import { EquityCurveChart } from "@/components/strategies/equity-curve-chart";
import { DrawdownChart } from "@/components/strategies/drawdown-chart";
import type { BacktestSummary, OhlcvBar, StrategyDetail } from "@/lib/api";

const BENCHMARK_SYMBOL = "^NSEI";

/**
 * REL-017 E17.3: a dedicated backtesting dashboard -- every metric here (sortino_ratio,
 * calmar_ratio, cagr, profit_factor, expectancy) was already real and returned by
 * BacktestSummary since Phase 4, just never rendered outside the Strategy Review Panel's
 * cramped 4-tile view (src/components/strategies/review-panel.tsx still shows only Sharpe/
 * MaxDD/WinRate/Trades). The Nifty 50 benchmark overlay is new: REL-016 E16.2 ingested real
 * ^NSEI data for the first time, closing the gap EquityCurveChart's own comment used to name
 * explicitly ("no Nifty 50 index data is ingested anywhere").
 *
 * Honest scope note: there is no per-run trade list here. The sandboxed strategy code's return
 * contract (PMPT-004, src/engine/sandbox/backtest_runner.py) is `{"metrics": {...},
 * "equity_curve": [...]}` -- individual trade records were never part of that contract or
 * persisted anywhere, so a trade list can't be shown without fabricating one. Documented here
 * rather than silently omitted.
 */
function BacktestingDashboardView() {
  const [selectedStrategyId, setSelectedStrategyId] = useState<string | null>(null);
  const [selectedBacktestId, setSelectedBacktestId] = useState<string | null>(null);

  const strategiesQuery = useQuery({ queryKey: ["strategies"], queryFn: api.strategies });
  const strategies = strategiesQuery.data ?? [];
  const effectiveStrategyId = selectedStrategyId ?? strategies[0]?.id ?? null;

  const detailQuery = useQuery({
    queryKey: ["strategy", effectiveStrategyId],
    queryFn: () => api.strategy(effectiveStrategyId!),
    enabled: !!effectiveStrategyId,
  });

  const allDetailsQuery = useQuery({
    queryKey: ["all-strategy-backtest-details"],
    queryFn: async () => Promise.all(strategies.map((s) => api.strategy(s.id))),
    enabled: strategies.length > 0,
  });

  const backtests = detailQuery.data?.backtests ?? [];
  const effectiveBacktestId = selectedBacktestId ?? backtests[0]?.id ?? null;
  const selectedBacktest = backtests.find((b) => b.id === effectiveBacktestId) ?? null;

  const equityCurveQuery = useQuery({
    queryKey: ["equity-curve", effectiveBacktestId],
    queryFn: () => api.equityCurve(effectiveBacktestId!),
    enabled: !!effectiveBacktestId && !!selectedBacktest?.has_equity_curve,
  });

  const benchmarkQuery = useQuery({
    queryKey: ["ohlcv", BENCHMARK_SYMBOL],
    queryFn: () => api.ohlcv(BENCHMARK_SYMBOL),
  });

  const equityCurveData = equityCurveQuery.data;
  const benchmarkData = benchmarkQuery.data;
  const points = useMemo(() => equityCurveData ?? [], [equityCurveData]);
  const benchmarkOverlay = useMemo(
    () => buildBenchmarkOverlay(points, benchmarkData ?? []),
    [points, benchmarkData],
  );

  return (
    <main className="mx-auto flex w-full max-w-[1440px] flex-1 flex-col gap-4 p-6 sm:p-8">
      <GlassCard eyebrow="Select" title="Strategy">
        {strategiesQuery.isLoading ? (
          <div className="h-9 animate-pulse rounded-lg bg-white/5" />
        ) : strategies.length === 0 ? (
          <p className="text-xs text-zinc-500">No strategies exist yet.</p>
        ) : (
          <select
            value={effectiveStrategyId ?? ""}
            onChange={(e) => {
              setSelectedStrategyId(e.target.value);
              setSelectedBacktestId(null);
            }}
            className="rounded-md border border-white/10 bg-black/30 px-2.5 py-1.5 text-xs text-zinc-200"
          >
            {strategies.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} ({s.status})
              </option>
            ))}
          </select>
        )}
      </GlassCard>

      {detailQuery.data && (
        <>
          <GlassCard eyebrow={detailQuery.data.status} title={detailQuery.data.name}>
            {backtests.length === 0 ? (
              <p className="text-xs text-zinc-500">No backtests run yet for this strategy.</p>
            ) : (
              <>
                <div className="mb-3 flex flex-wrap gap-1.5">
                  {backtests.map((b) => (
                    <button
                      key={b.id}
                      onClick={() => setSelectedBacktestId(b.id)}
                      className={
                        b.id === effectiveBacktestId
                          ? "rounded-full bg-white/10 px-2.5 py-1 text-[10px] font-medium text-zinc-100"
                          : "rounded-full bg-white/5 px-2.5 py-1 text-[10px] font-medium text-zinc-500 hover:text-zinc-300"
                      }
                    >
                      {new Date(b.created_at).toLocaleDateString("en-IN")}
                    </button>
                  ))}
                </div>
                {selectedBacktest && <FullMetricGrid backtest={selectedBacktest} />}
              </>
            )}
          </GlassCard>

          {selectedBacktest && (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <GlassCard eyebrow="Performance" title="Equity Curve vs Nifty 50">
                <EquityCurveChart points={points} benchmark={benchmarkOverlay} />
              </GlassCard>
              <GlassCard eyebrow="Risk" title="Drawdown from Peak">
                <DrawdownChart points={points} />
              </GlassCard>
            </div>
          )}

          <GlassCard eyebrow="Cross-run" title="All backtests for this strategy">
            {backtests.length === 0 ? (
              <p className="text-xs text-zinc-500">No backtests to compare yet.</p>
            ) : (
              <BacktestComparisonTable rows={backtests.map((b) => ({ label: fmtDate(b.created_at), backtest: b }))} />
            )}
          </GlassCard>
        </>
      )}

      <GlassCard eyebrow="Cross-strategy" title="Latest backtest per strategy">
        {allDetailsQuery.isLoading ? (
          <div className="h-32 animate-pulse rounded-xl bg-white/5" />
        ) : (
          <BacktestComparisonTable
            rows={(allDetailsQuery.data ?? [])
              .filter((d): d is StrategyDetail & { backtests: BacktestSummary[] } => d.backtests.length > 0)
              .map((d) => ({ label: d.name, backtest: d.backtests[0] }))}
          />
        )}
      </GlassCard>

      <GlassCard eyebrow="Scope note" title="No per-run trade list">
        <p className="text-[11px] leading-relaxed text-zinc-500">
          A backtest here only ever returns aggregate metrics and an equity curve (the sandboxed
          strategy code&apos;s own return contract, PMPT-004) — individual trade records were
          never computed or persisted anywhere in this pipeline, so there is no real per-trade
          list to show without fabricating one. Real, per-trade fills do exist for the Paper
          Trading Desk (a live, ongoing ledger, not a backtest artifact) — see{" "}
          <code className="text-zinc-400">/paper-trading</code>.
        </p>
      </GlassCard>

      <GlassCard eyebrow="Scope note" title="Monte Carlo p95 drawdown reads blank; no Walk-Forward view">
        <p className="text-[11px] leading-relaxed text-zinc-500">
          <code className="text-zinc-400">MC p95 DD</code> above is a real database column
          (DB-007) exposed here for the first time, not a fabricated one — but it reads blank for
          every backtest today because nothing in this pipeline has ever populated it outside its
          own test file. Running a real simulation (
          <code className="text-zinc-400">run_monte_carlo_simulation()</code>) needs per-trade
          returns, which the sandbox contract above never captures either — closing this for real
          means extending that contract and re-running backtests, not just adding UI on top of
          data that already exists, so it&apos;s deliberately left as an honest gap rather than
          stretched into this pass. Walk-Forward Optimization results have the same real gap one
          level deeper: no persistence layer or API endpoint exists for{" "}
          <code className="text-zinc-400">walk_forward.py</code>&apos;s output at all (only unit
          tests call it directly) — there is nothing yet to build this view against.
        </p>
      </GlassCard>
    </main>
  );
}

function buildBenchmarkOverlay(
  points: { date: string }[],
  benchmarkBars: OhlcvBar[],
): (number | null)[] | undefined {
  if (points.length === 0 || benchmarkBars.length === 0) return undefined;
  const byDate = new Map(benchmarkBars.map((b) => [b.date, b.close]));
  const firstMatch = points.find((p) => byDate.has(p.date));
  if (!firstMatch) return undefined;
  const base = byDate.get(firstMatch.date)!;
  return points.map((p) => {
    const close = byDate.get(p.date);
    return close !== undefined ? (close / base) * 100 : null;
  });
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IN");
}

const METRICS: { key: keyof BacktestSummary; label: string; fmt: (v: number) => string }[] = [
  { key: "sharpe_ratio", label: "Sharpe", fmt: (v) => v.toFixed(2) },
  { key: "sortino_ratio", label: "Sortino", fmt: (v) => v.toFixed(2) },
  { key: "calmar_ratio", label: "Calmar", fmt: (v) => v.toFixed(2) },
  { key: "max_drawdown", label: "Max DD", fmt: (v) => `${(v * 100).toFixed(1)}%` },
  { key: "cagr", label: "CAGR", fmt: (v) => `${(v * 100).toFixed(1)}%` },
  { key: "win_rate", label: "Win Rate", fmt: (v) => `${(v * 100).toFixed(0)}%` },
  { key: "profit_factor", label: "Profit Factor", fmt: (v) => v.toFixed(2) },
  { key: "expectancy", label: "Expectancy", fmt: (v) => `₹${v.toFixed(2)}` },
  { key: "total_trades", label: "Trades", fmt: (v) => v.toString() },
  {
    key: "monte_carlo_p95_max_drawdown",
    label: "MC p95 DD",
    fmt: (v) => `${(v * 100).toFixed(1)}%`,
  },
];

function FullMetricGrid({ backtest }: { backtest: BacktestSummary }) {
  return (
    <div className="grid grid-cols-3 gap-2 sm:grid-cols-5 lg:grid-cols-10">
      {METRICS.map(({ key, label, fmt }) => {
        const raw = backtest[key];
        return (
          <div key={key} className="rounded-lg bg-white/[0.03] p-2 text-center">
            <div className="font-mono-tabular text-sm font-semibold text-zinc-100">
              {typeof raw === "number" ? fmt(raw) : "—"}
            </div>
            <div className="text-[9px] uppercase tracking-wider text-zinc-500">{label}</div>
          </div>
        );
      })}
    </div>
  );
}

function BacktestComparisonTable({ rows }: { rows: { label: string; backtest: BacktestSummary }[] }) {
  if (rows.length === 0) {
    return <p className="text-xs text-zinc-500">Nothing to compare yet.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-[11px]">
        <thead>
          <tr className="text-[9px] uppercase tracking-wider text-zinc-600">
            <th className="pb-2 pr-3">Run</th>
            {METRICS.map((m) => (
              <th key={m.key} className="pb-2 pr-3 text-right">
                {m.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(({ label, backtest }) => (
            <tr key={backtest.id} className="border-t border-white/5">
              <td className="py-1.5 pr-3 text-zinc-300">{label}</td>
              {METRICS.map(({ key, fmt }) => {
                const raw = backtest[key];
                return (
                  <td key={key} className="py-1.5 pr-3 text-right font-mono-tabular text-zinc-400">
                    {typeof raw === "number" ? fmt(raw) : "—"}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function BacktestsPage() {
  return (
    <RequireAuth>
      <TopBar connected={false} subtitle="Backtesting Dashboard — Full Metrics & Comparison" />
      <BacktestingDashboardView />
    </RequireAuth>
  );
}
