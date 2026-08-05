"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api } from "@/lib/api";
import { RequireAuth } from "@/lib/auth";
import { Sidebar } from "@/components/layout/sidebar";
import { PageHeader } from "@/components/layout/page-header";
import { Card } from "@/components/ui/card";
import { EquityCurveChart } from "@/components/strategies/equity-curve-chart";
import { DrawdownChart } from "@/components/strategies/drawdown-chart";
import type {
  BacktestSummary,
  OhlcvBar,
  StrategyDetail,
  TradeSummary,
  WalkForwardWindow,
} from "@/lib/api";

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
 * REL-023 E23.3: the per-run trade list this component's own docstring used to say couldn't
 * exist -- REL-022 extended the sandboxed contract to capture a real per-trade ledger, and this
 * page now renders it via GET .../trades. Empty (not missing) for a backtest that predates that
 * contract or genuinely closed zero trades in its window.
 *
 * REL-024 E24.3: the Walk-Forward Optimization view this component's own scope-note card used to
 * say had nothing to build against -- an adapter now exists from the sandboxed strategy's real
 * entries/exits signals to walk_forward.py's rolling-window contract, and this page renders the
 * real per-window pass/fail results via GET .../walk-forward. Empty (not missing) for a backtest
 * that predates the contract, or one with too little real history for even one rolling window.
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

  const tradesQuery = useQuery({
    queryKey: ["backtest-trades", effectiveBacktestId],
    queryFn: () => api.backtestTrades(effectiveBacktestId!),
    enabled: !!effectiveBacktestId,
  });

  const walkForwardQuery = useQuery({
    queryKey: ["backtest-walk-forward", effectiveBacktestId],
    queryFn: () => api.backtestWalkForward(effectiveBacktestId!),
    enabled: !!effectiveBacktestId,
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
      <Card eyebrow="Select" title="Strategy">
        {strategiesQuery.isLoading ? (
          <div className="h-9 animate-pulse rounded-lg bg-bg" />
        ) : strategies.length === 0 ? (
          <p className="text-xs text-text-faint">No strategies exist yet.</p>
        ) : (
          <select
            value={effectiveStrategyId ?? ""}
            onChange={(e) => {
              setSelectedStrategyId(e.target.value);
              setSelectedBacktestId(null);
            }}
            className="rounded-md border border-card-edge bg-bg px-2.5 py-1.5 text-xs text-text"
          >
            {strategies.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} ({s.status})
              </option>
            ))}
          </select>
        )}
      </Card>

      {detailQuery.data && (
        <>
          <Card eyebrow={detailQuery.data.status} title={detailQuery.data.name}>
            {backtests.length === 0 ? (
              <p className="text-xs text-text-faint">No backtests run yet for this strategy.</p>
            ) : (
              <>
                <div className="mb-3 flex flex-wrap gap-1.5">
                  {backtests.map((b) => (
                    <button
                      key={b.id}
                      onClick={() => setSelectedBacktestId(b.id)}
                      className={
                        b.id === effectiveBacktestId
                          ? "rounded-full bg-panel px-2.5 py-1 text-[10px] font-medium text-text"
                          : "rounded-full bg-bg px-2.5 py-1 text-[10px] font-medium text-text-faint hover:text-text-dim"
                      }
                    >
                      {new Date(b.created_at).toLocaleDateString("en-IN")}
                    </button>
                  ))}
                </div>
                {selectedBacktest && <FullMetricGrid backtest={selectedBacktest} />}
              </>
            )}
          </Card>

          {selectedBacktest && (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <Card eyebrow="Performance" title="Equity Curve vs Nifty 50">
                <EquityCurveChart points={points} benchmark={benchmarkOverlay} />
              </Card>
              <Card eyebrow="Risk" title="Drawdown from Peak">
                <DrawdownChart points={points} />
              </Card>
            </div>
          )}

          <Card eyebrow="Cross-run" title="All backtests for this strategy">
            {backtests.length === 0 ? (
              <p className="text-xs text-text-faint">No backtests to compare yet.</p>
            ) : (
              <BacktestComparisonTable rows={backtests.map((b) => ({ label: fmtDate(b.created_at), backtest: b }))} />
            )}
          </Card>
        </>
      )}

      <Card eyebrow="Cross-strategy" title="Latest backtest per strategy">
        {allDetailsQuery.isLoading ? (
          <div className="h-32 animate-pulse rounded-xl bg-bg" />
        ) : (
          <BacktestComparisonTable
            rows={(allDetailsQuery.data ?? [])
              .filter((d): d is StrategyDetail & { backtests: BacktestSummary[] } => d.backtests.length > 0)
              .map((d) => ({ label: d.name, backtest: d.backtests[0] }))}
          />
        )}
      </Card>

      {selectedBacktest && (
        <Card eyebrow="Per-trade" title="Trade List">
          <TradeListTable trades={tradesQuery.data} isLoading={tradesQuery.isLoading} />
        </Card>
      )}

      {selectedBacktest && (
        <Card eyebrow="Rolling out-of-sample" title="Walk-Forward Optimization">
          <WalkForwardTable
            windows={walkForwardQuery.data}
            isLoading={walkForwardQuery.isLoading}
          />
        </Card>
      )}
    </main>
  );
}

function WalkForwardTable({
  windows,
  isLoading,
}: {
  windows: WalkForwardWindow[] | undefined;
  isLoading: boolean;
}) {
  if (isLoading) {
    return <div className="h-24 animate-pulse rounded-xl bg-bg" />;
  }
  if (!windows || windows.length === 0) {
    return (
      <p className="text-[11px] leading-relaxed text-text-faint">
        No Walk-Forward windows for this backtest — either its real entries/exits and price
        history don&apos;t span enough time for even one full rolling window, or it predates the
        real Walk-Forward contract (REL-024, 2026-08-05) and can&apos;t be backfilled.
      </p>
    );
  }
  const passedCount = windows.filter((w) => w.out_of_sample_passed).length;
  return (
    <div>
      <p className="mb-2 text-[11px] text-text-faint">
        {passedCount} / {windows.length} rolling windows passed the Phase 6 out-of-sample
        positive-expectancy rule.
      </p>
      <div className="max-h-80 overflow-y-auto overflow-x-auto">
        <table className="w-full text-left text-[11px]">
          <thead className="sticky top-0 bg-panel">
            <tr className="text-[9px] uppercase tracking-wider text-text-faint">
              <th className="pb-2 pr-3">Train Window</th>
              <th className="pb-2 pr-3">Test Window</th>
              <th className="pb-2 pr-3 text-right">Train Expectancy</th>
              <th className="pb-2 pr-3 text-right">Test Expectancy</th>
              <th className="pb-2 pr-3 text-right">Test Sharpe</th>
              <th className="pb-2 pr-3 text-right">Test Trades</th>
              <th className="pb-2 text-right">Out-of-Sample</th>
            </tr>
          </thead>
          <tbody>
            {windows.map((w, i) => (
              <tr key={`${w.train_start}-${i}`} className="border-t border-card-edge">
                <td className="py-1.5 pr-3 text-text-dim">
                  {w.train_start} → {w.train_end}
                </td>
                <td className="py-1.5 pr-3 text-text-dim">
                  {w.test_start} → {w.test_end}
                </td>
                <td className="py-1.5 pr-3 text-right font-mono-tabular text-text-faint">
                  {w.train_expectancy !== null ? `₹${w.train_expectancy.toFixed(2)}` : "—"}
                </td>
                <td
                  className={
                    w.test_expectancy !== null && w.test_expectancy >= 0
                      ? "py-1.5 pr-3 text-right font-mono-tabular text-up"
                      : w.test_expectancy !== null
                        ? "py-1.5 pr-3 text-right font-mono-tabular text-down"
                        : "py-1.5 pr-3 text-right font-mono-tabular text-text-faint"
                  }
                >
                  {w.test_expectancy !== null ? `₹${w.test_expectancy.toFixed(2)}` : "—"}
                </td>
                <td className="py-1.5 pr-3 text-right font-mono-tabular text-text-faint">
                  {w.test_sharpe_ratio !== null ? w.test_sharpe_ratio.toFixed(2) : "—"}
                </td>
                <td className="py-1.5 pr-3 text-right font-mono-tabular text-text-faint">
                  {w.test_total_trades ?? "—"}
                </td>
                <td
                  className={
                    w.out_of_sample_passed
                      ? "py-1.5 text-right font-medium text-up"
                      : "py-1.5 text-right font-medium text-down"
                  }
                >
                  {w.out_of_sample_passed ? "Pass" : "Fail"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TradeListTable({
  trades,
  isLoading,
}: {
  trades: TradeSummary[] | undefined;
  isLoading: boolean;
}) {
  if (isLoading) {
    return <div className="h-24 animate-pulse rounded-xl bg-bg" />;
  }
  if (!trades || trades.length === 0) {
    return (
      <p className="text-[11px] leading-relaxed text-text-faint">
        No closed trades in this backtest&apos;s window — either it genuinely closed zero real
        trades, or it predates the real trade-ledger contract (REL-022, 2026-08-05) and can&apos;t
        be backfilled.
      </p>
    );
  }
  return (
    <div className="max-h-80 overflow-y-auto overflow-x-auto">
      <table className="w-full text-left text-[11px]">
        <thead className="sticky top-0 bg-panel">
          <tr className="text-[9px] uppercase tracking-wider text-text-faint">
            <th className="pb-2 pr-3">Entry</th>
            <th className="pb-2 pr-3">Exit</th>
            <th className="pb-2 pr-3">Side</th>
            <th className="pb-2 pr-3 text-right">Size</th>
            <th className="pb-2 pr-3 text-right">Entry Px</th>
            <th className="pb-2 pr-3 text-right">Exit Px</th>
            <th className="pb-2 pr-3 text-right">PnL</th>
            <th className="pb-2 text-right">Return</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t, i) => (
            <tr key={`${t.entry_date}-${i}`} className="border-t border-card-edge">
              <td className="py-1.5 pr-3 text-text-dim">{t.entry_date}</td>
              <td className="py-1.5 pr-3 text-text-dim">{t.exit_date}</td>
              <td
                className={
                  t.side === "long"
                    ? "py-1.5 pr-3 font-medium text-up"
                    : "py-1.5 pr-3 font-medium text-down"
                }
              >
                {t.side}
              </td>
              <td className="py-1.5 pr-3 text-right font-mono-tabular text-text-faint">
                {t.size.toFixed(2)}
              </td>
              <td className="py-1.5 pr-3 text-right font-mono-tabular text-text-faint">
                ₹{t.entry_price.toFixed(2)}
              </td>
              <td className="py-1.5 pr-3 text-right font-mono-tabular text-text-faint">
                ₹{t.exit_price.toFixed(2)}
              </td>
              <td
                className={
                  t.pnl >= 0
                    ? "py-1.5 pr-3 text-right font-mono-tabular text-up"
                    : "py-1.5 pr-3 text-right font-mono-tabular text-down"
                }
              >
                ₹{t.pnl.toFixed(2)}
              </td>
              <td
                className={
                  t.return_pct >= 0
                    ? "py-1.5 text-right font-mono-tabular text-up"
                    : "py-1.5 text-right font-mono-tabular text-down"
                }
              >
                {(t.return_pct * 100).toFixed(2)}%
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
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
          <div key={key} className="rounded-lg bg-bg p-2 text-center">
            <div className="font-mono-tabular text-sm font-semibold text-text">
              {typeof raw === "number" ? fmt(raw) : "—"}
            </div>
            <div className="text-[9px] uppercase tracking-wider text-text-faint">{label}</div>
          </div>
        );
      })}
    </div>
  );
}

function BacktestComparisonTable({ rows }: { rows: { label: string; backtest: BacktestSummary }[] }) {
  if (rows.length === 0) {
    return <p className="text-xs text-text-faint">Nothing to compare yet.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-[11px]">
        <thead>
          <tr className="text-[9px] uppercase tracking-wider text-text-faint">
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
            <tr key={backtest.id} className="border-t border-card-edge">
              <td className="py-1.5 pr-3 text-text-dim">{label}</td>
              {METRICS.map(({ key, fmt }) => {
                const raw = backtest[key];
                return (
                  <td key={key} className="py-1.5 pr-3 text-right font-mono-tabular text-text-faint">
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
      <div className="flex flex-1">
        <Sidebar />
        <div className="flex flex-1 flex-col">
          <PageHeader connected={false} subtitle="Backtesting Dashboard — Full Metrics & Comparison" />
          <BacktestingDashboardView />
        </div>
      </div>
    </RequireAuth>
  );
}
