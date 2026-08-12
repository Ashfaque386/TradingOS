"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { BacktestComparisonTable } from "./comparison-table";
import { CompareEquityCurveChart } from "./compare-equity-curve-chart";

/** REL-042: renders once 2+ runs are selected (checkboxes on the cross-strategy comparison
 * table below, state lives in the page's own `?compare=` URL param) -- a real KPI grid plus a
 * real multi-run equity-curve overlay in one round trip via GET /strategies/backtests/compare. */
export function CompareWorkspace({ ids }: { ids: string[] }) {
  const query = useQuery({
    queryKey: ["compare-backtests", ids],
    queryFn: () => api.compareBacktests(ids),
    enabled: ids.length >= 2,
  });

  if (ids.length < 2) {
    return (
      <p className="text-xs text-text-faint">
        Select at least 2 runs above (checkboxes) to compare them here.
      </p>
    );
  }
  if (query.isLoading) {
    return <div className="h-64 animate-pulse rounded-xl bg-bg" />;
  }
  const rows = query.data ?? [];
  if (rows.length === 0) {
    return <p className="text-xs text-text-faint">None of the selected runs could be found.</p>;
  }

  return (
    <div className="flex flex-col gap-4">
      <BacktestComparisonTable
        rows={rows.map((r) => ({
          id: r.id,
          label: `${r.strategy_name} · ${new Date(r.created_at).toLocaleDateString("en-IN")}`,
          backtest: r,
        }))}
      />
      <CompareEquityCurveChart rows={rows} />
    </div>
  );
}
