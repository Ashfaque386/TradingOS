"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { usePageStatus } from "@/hooks/usePageStatus";
import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
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
export default function BacktestsPage() {
  const [selectedStrategyId, setSelectedStrategyId] = useState<string | null>(null);
  const [selectedBacktestId, setSelectedBacktestId] = useState<string | null>(null);

  usePageStatus("Backtesting Dashboard — Full Metrics & Comparison", false);

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
              <div className="flex flex-wrap gap-1.5">
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
            )}
          </Card>

          {selectedBacktest && (
            <Card eyebrow="Snapshot" title="Key Metrics">
              <FullMetricGrid backtest={selectedBacktest} />
            </Card>
          )}

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
        <Table className="text-[11px]">
          <TableHeader className="sticky top-0 z-10 bg-panel">
            <TableRow className="text-[9px] uppercase tracking-wider text-text-faint hover:bg-transparent">
              <TableHead className="h-auto px-0 pb-2 pr-3 font-normal">Train Window</TableHead>
              <TableHead className="h-auto px-0 pb-2 pr-3 font-normal">Test Window</TableHead>
              <TableHead className="h-auto px-0 pb-2 pr-3 text-right font-normal">Train Expectancy</TableHead>
              <TableHead className="h-auto px-0 pb-2 pr-3 text-right font-normal">Test Expectancy</TableHead>
              <TableHead className="h-auto px-0 pb-2 pr-3 text-right font-normal">Test Sharpe</TableHead>
              <TableHead className="h-auto px-0 pb-2 pr-3 text-right font-normal">Test Trades</TableHead>
              <TableHead className="h-auto px-0 pb-2 text-right font-normal">Out-of-Sample</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {windows.map((w, i) => (
              <TableRow key={`${w.train_start}-${i}`} className="border-card-edge">
                <TableCell className="px-0 py-1.5 pr-3 text-text-dim">
                  {w.train_start} → {w.train_end}
                </TableCell>
                <TableCell className="px-0 py-1.5 pr-3 text-text-dim">
                  {w.test_start} → {w.test_end}
                </TableCell>
                <TableCell className="px-0 py-1.5 pr-3 text-right font-mono-tabular text-text-faint">
                  {w.train_expectancy !== null ? `₹${w.train_expectancy.toFixed(2)}` : "—"}
                </TableCell>
                <TableCell
                  className={cn(
                    "px-0 py-1.5 pr-3 text-right font-mono-tabular",
                    w.test_expectancy !== null && w.test_expectancy >= 0
                      ? "text-up"
                      : w.test_expectancy !== null
                        ? "text-down"
                        : "text-text-faint",
                  )}
                >
                  {w.test_expectancy !== null ? `₹${w.test_expectancy.toFixed(2)}` : "—"}
                </TableCell>
                <TableCell className="px-0 py-1.5 pr-3 text-right font-mono-tabular text-text-faint">
                  {w.test_sharpe_ratio !== null ? w.test_sharpe_ratio.toFixed(2) : "—"}
                </TableCell>
                <TableCell className="px-0 py-1.5 pr-3 text-right font-mono-tabular text-text-faint">
                  {w.test_total_trades ?? "—"}
                </TableCell>
                <TableCell
                  className={cn(
                    "px-0 py-1.5 text-right font-medium",
                    w.out_of_sample_passed ? "text-up" : "text-down",
                  )}
                >
                  {w.out_of_sample_passed ? "Pass" : "Fail"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
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
      <Table className="text-[11px]">
        <TableHeader className="sticky top-0 z-10 bg-panel">
          <TableRow className="text-[9px] uppercase tracking-wider text-text-faint hover:bg-transparent">
            <TableHead className="h-auto px-0 pb-2 pr-3 font-normal">Entry</TableHead>
            <TableHead className="h-auto px-0 pb-2 pr-3 font-normal">Exit</TableHead>
            <TableHead className="h-auto px-0 pb-2 pr-3 font-normal">Side</TableHead>
            <TableHead className="h-auto px-0 pb-2 pr-3 text-right font-normal">Size</TableHead>
            <TableHead className="h-auto px-0 pb-2 pr-3 text-right font-normal">Entry Px</TableHead>
            <TableHead className="h-auto px-0 pb-2 pr-3 text-right font-normal">Exit Px</TableHead>
            <TableHead className="h-auto px-0 pb-2 pr-3 text-right font-normal">PnL</TableHead>
            <TableHead className="h-auto px-0 pb-2 text-right font-normal">Return</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {trades.map((t, i) => (
            <TableRow key={`${t.entry_date}-${i}`} className="border-card-edge">
              <TableCell className="px-0 py-1.5 pr-3 text-text-dim">{t.entry_date}</TableCell>
              <TableCell className="px-0 py-1.5 pr-3 text-text-dim">{t.exit_date}</TableCell>
              <TableCell
                className={cn(
                  "px-0 py-1.5 pr-3 font-medium",
                  t.side === "long" ? "text-up" : "text-down",
                )}
              >
                {t.side}
              </TableCell>
              <TableCell className="px-0 py-1.5 pr-3 text-right font-mono-tabular text-text-faint">
                {t.size.toFixed(2)}
              </TableCell>
              <TableCell className="px-0 py-1.5 pr-3 text-right font-mono-tabular text-text-faint">
                ₹{t.entry_price.toFixed(2)}
              </TableCell>
              <TableCell className="px-0 py-1.5 pr-3 text-right font-mono-tabular text-text-faint">
                ₹{t.exit_price.toFixed(2)}
              </TableCell>
              <TableCell
                className={cn(
                  "px-0 py-1.5 pr-3 text-right font-mono-tabular",
                  t.pnl >= 0 ? "text-up" : "text-down",
                )}
              >
                ₹{t.pnl.toFixed(2)}
              </TableCell>
              <TableCell
                className={cn(
                  "px-0 py-1.5 text-right font-mono-tabular",
                  t.return_pct >= 0 ? "text-up" : "text-down",
                )}
              >
                {(t.return_pct * 100).toFixed(2)}%
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
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

const METRICS: {
  key: keyof BacktestSummary;
  label: string;
  fmt: (v: number) => string;
  /** Only set for metrics with an unambiguous, standard good/bad threshold -- avoids guessing at
   * a sign convention (e.g. drawdown) that isn't worth risking a wrong-direction color cue on. */
  tone?: (v: number) => "up" | "warn" | "down";
}[] = [
  {
    key: "sharpe_ratio",
    label: "Sharpe",
    fmt: (v) => v.toFixed(2),
    tone: (v) => (v >= 1 ? "up" : v >= 0 ? "warn" : "down"),
  },
  { key: "sortino_ratio", label: "Sortino", fmt: (v) => v.toFixed(2) },
  { key: "calmar_ratio", label: "Calmar", fmt: (v) => v.toFixed(2) },
  { key: "max_drawdown", label: "Max DD", fmt: (v) => `${(v * 100).toFixed(1)}%` },
  { key: "cagr", label: "CAGR", fmt: (v) => `${(v * 100).toFixed(1)}%` },
  {
    key: "win_rate",
    label: "Win Rate",
    fmt: (v) => `${(v * 100).toFixed(0)}%`,
    tone: (v) => (v >= 0.5 ? "up" : v >= 0.4 ? "warn" : "down"),
  },
  { key: "profit_factor", label: "Profit Factor", fmt: (v) => v.toFixed(2) },
  { key: "expectancy", label: "Expectancy", fmt: (v) => `₹${v.toFixed(2)}` },
  { key: "total_trades", label: "Trades", fmt: (v) => v.toString() },
  {
    key: "monte_carlo_p95_max_drawdown",
    label: "MC p95 DD",
    fmt: (v) => `${(v * 100).toFixed(1)}%`,
  },
];

const TONE_CLASS: Record<"up" | "warn" | "down", string> = {
  up: "text-up",
  warn: "text-warn",
  down: "text-down",
};

function FullMetricGrid({ backtest }: { backtest: BacktestSummary }) {
  return (
    <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-5 lg:grid-cols-10">
      {METRICS.map(({ key, label, fmt, tone }) => {
        const raw = backtest[key];
        const isNum = typeof raw === "number";
        const toneClass = isNum && tone ? TONE_CLASS[tone(raw)] : "text-text";
        return (
          <div
            key={key}
            className="rounded-btn border border-card-edge bg-bg p-3 text-center transition-colors hover:border-text-faint/40"
          >
            <div className={cn("font-mono-tabular text-base font-semibold", toneClass)}>
              {isNum ? fmt(raw) : "—"}
            </div>
            <div className="mt-0.5 text-[9px] uppercase tracking-wider text-text-faint">{label}</div>
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
      <Table className="text-[11px]">
        <TableHeader>
          <TableRow className="text-[9px] uppercase tracking-wider text-text-faint hover:bg-transparent">
            <TableHead className="h-auto px-0 pb-2 pr-3 font-normal">Run</TableHead>
            {METRICS.map((m) => (
              <TableHead key={m.key} className="h-auto px-0 pb-2 pr-3 text-right font-normal">
                {m.label}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map(({ label, backtest }) => (
            <TableRow key={backtest.id} className="border-card-edge">
              <TableCell className="px-0 py-1.5 pr-3 text-text-dim">{label}</TableCell>
              {METRICS.map(({ key, fmt }) => {
                const raw = backtest[key];
                return (
                  <TableCell key={key} className="px-0 py-1.5 pr-3 text-right font-mono-tabular text-text-faint">
                    {typeof raw === "number" ? fmt(raw) : "—"}
                  </TableCell>
                );
              })}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
