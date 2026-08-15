"use client";

import { useQuery } from "@tanstack/react-query";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo } from "react";
import { api } from "@/lib/api";
import { usePageStatus } from "@/hooks/usePageStatus";
import { Card } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EquityCurveChart, buildBenchmarkOverlay } from "@/components/strategies/equity-curve-chart";
import { DrawdownChart } from "@/components/strategies/drawdown-chart";
import { StrategyPicker } from "@/components/backtests/strategy-picker";
import { RunBacktestButton } from "@/components/backtests/run-backtest-button";
import { VerdictPanel } from "@/components/backtests/verdict-panel";
import { FullMetricGrid } from "@/components/backtests/metric-grid";
import { BacktestComparisonTable } from "@/components/backtests/comparison-table";
import { TradeListTable } from "@/components/backtests/trade-list-table";
import { WalkForwardTable } from "@/components/backtests/walk-forward-table";
import { MonteCarloHistogram } from "@/components/backtests/monte-carlo-histogram";
import { TradePnlHistogram } from "@/components/backtests/trade-pnl-histogram";
import { CompareWorkspace } from "@/components/backtests/compare-workspace";
import { ExportButton } from "@/components/backtests/export-button";

const BENCHMARK_SYMBOL = "^NSEI";
const MAX_COMPARE = 6;

/**
 * REL-017 E17.3, rebuilt REL-040/041: every metric here (sortino_ratio, calmar_ratio, cagr,
 * profit_factor, expectancy) was already real, just never rendered outside the Strategy Review
 * Panel's cramped 4-tile view. The Nifty 50 benchmark overlay, per-trade ledger (REL-022/023) and
 * Walk-Forward view (REL-024) are all real, already-wired data -- nothing here is rebuilt.
 *
 * REL-040/041 adds: the 8 real AI-pipeline verdict fields (previously computed, never returned by
 * any endpoint -- see VerdictPanel), a real backtest_count-aware strategy picker, a Run New
 * Backtest trigger (this page had no way to launch a run, only view past ones), URL-addressable
 * state (?strategy=&run=&tab=, bookmarkable and no longer reset on refresh), and a real server-
 * side "latest per strategy" cross-strategy view (GET /strategies/backtests/latest) replacing the
 * previous N+1 client-side fetch (one GET /strategies/{id} per strategy).
 */
export default function BacktestsPage() {
  return (
    <Suspense fallback={<main className="mx-auto flex w-full max-w-[1440px] flex-1 flex-col gap-4 p-6 sm:p-8" />}>
      <BacktestsPageInner />
    </Suspense>
  );
}

function BacktestsPageInner() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  usePageStatus("Backtesting Dashboard — Full Metrics & Comparison", false);

  const urlStrategyId = searchParams.get("strategy");
  const urlBacktestId = searchParams.get("run");
  const activeTab = searchParams.get("tab") ?? "trades";
  const compareIds = useMemo(() => {
    const raw = searchParams.get("compare");
    return raw ? raw.split(",").filter(Boolean) : [];
  }, [searchParams]);

  function updateParams(next: Record<string, string | null>) {
    const params = new URLSearchParams(searchParams.toString());
    for (const [key, value] of Object.entries(next)) {
      if (value === null) params.delete(key);
      else params.set(key, value);
    }
    router.replace(`${pathname}?${params.toString()}`, { scroll: false });
  }

  function toggleCompare(id: string) {
    const next = compareIds.includes(id)
      ? compareIds.filter((x) => x !== id)
      : [...compareIds, id].slice(0, MAX_COMPARE);
    updateParams({ compare: next.length > 0 ? next.join(",") : null });
  }

  const strategiesQuery = useQuery({ queryKey: ["strategies"], queryFn: api.strategies });
  const strategies = strategiesQuery.data ?? [];
  const effectiveStrategyId = urlStrategyId ?? strategies[0]?.id ?? null;

  const detailQuery = useQuery({
    queryKey: ["strategy", effectiveStrategyId],
    queryFn: () => api.strategy(effectiveStrategyId!),
    enabled: !!effectiveStrategyId,
  });

  const latestBacktestsQuery = useQuery({
    queryKey: ["latest-backtests"],
    queryFn: api.latestBacktests,
  });

  const backtests = detailQuery.data?.backtests ?? [];
  const effectiveBacktestId = urlBacktestId ?? backtests[0]?.id ?? null;
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
      <Card
        eyebrow="Select"
        title="Strategy"
        action={
          effectiveStrategyId && (
            <RunBacktestButton
              strategyId={effectiveStrategyId}
              onCompleted={(backtestId) => updateParams({ run: backtestId })}
            />
          )
        }
      >
        <StrategyPicker
          strategies={strategies}
          value={effectiveStrategyId}
          isLoading={strategiesQuery.isLoading}
          onChange={(id) => updateParams({ strategy: id, run: null })}
        />
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
                    onClick={() => updateParams({ run: b.id })}
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
            <Card eyebrow="AI Pipeline" title="Go / No-Go Verdict">
              <VerdictPanel backtest={selectedBacktest} />
            </Card>
          )}

          {selectedBacktest && (
            <Card eyebrow="Snapshot" title="Key Metrics">
              <FullMetricGrid backtest={selectedBacktest} />
            </Card>
          )}

          {selectedBacktest && (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <Card eyebrow="Performance" title="Equity Curve vs Nifty 50">
                <EquityCurveChart points={points} benchmark={benchmarkOverlay} trades={tradesQuery.data} />
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
              <BacktestComparisonTable
                rows={backtests.map((b) => ({ id: b.id, label: fmtDate(b.created_at), backtest: b }))}
              />
            )}
          </Card>
        </>
      )}

      <Card eyebrow="Cross-strategy" title="Latest backtest per strategy">
        <p className="mb-2 text-[10px] text-text-faint">
          Tick up to {MAX_COMPARE} runs to overlay them in the Comparison Workspace below.
        </p>
        {latestBacktestsQuery.isLoading ? (
          <div className="h-32 animate-pulse rounded-xl bg-bg" />
        ) : (
          <BacktestComparisonTable
            rows={(latestBacktestsQuery.data ?? []).map((b) => ({
              id: b.id,
              label: b.strategy_name,
              backtest: b,
            }))}
            selectedIds={new Set(compareIds)}
            onToggle={toggleCompare}
            maxSelected={MAX_COMPARE}
          />
        )}
      </Card>

      <Card eyebrow="REL-042" title="Comparison Workspace">
        <CompareWorkspace ids={compareIds} />
      </Card>

      {selectedBacktest && (
        <Card
          eyebrow="Detail"
          title="Per-Run Analysis"
          action={<ExportButton backtestId={selectedBacktest.id} />}
        >
          <Tabs value={activeTab} onValueChange={(v) => updateParams({ tab: v as string })}>
            <TabsList>
              <TabsTrigger value="trades">Trade List</TabsTrigger>
              <TabsTrigger value="walk-forward">Walk-Forward</TabsTrigger>
              <TabsTrigger value="monte-carlo">Monte Carlo</TabsTrigger>
              <TabsTrigger value="pnl-distribution">PnL Distribution</TabsTrigger>
            </TabsList>
            <TabsContent value="trades">
              <TradeListTable trades={tradesQuery.data} isLoading={tradesQuery.isLoading} />
            </TabsContent>
            <TabsContent value="walk-forward">
              <WalkForwardTable windows={walkForwardQuery.data} isLoading={walkForwardQuery.isLoading} />
            </TabsContent>
            <TabsContent value="monte-carlo">
              <MonteCarloHistogram backtestId={selectedBacktest.id} />
            </TabsContent>
            <TabsContent value="pnl-distribution">
              <TradePnlHistogram trades={tradesQuery.data} />
            </TabsContent>
          </Tabs>
        </Card>
      )}
    </main>
  );
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IN");
}
