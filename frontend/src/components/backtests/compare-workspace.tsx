"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { BacktestComparisonTable } from "./comparison-table";
import { CompareEquityCurveChart } from "./compare-equity-curve-chart";
import { CompareMetricsChart } from "./compare-metrics-chart";
import { CorrelationMatrix } from "./correlation-matrix";

/** REL-042: renders once 2+ runs are selected (checkboxes on the cross-strategy comparison
 * table below, state lives in the page's own `?compare=` URL param) -- a real KPI grid plus a
 * real multi-run equity-curve overlay in one round trip via GET /strategies/backtests/compare.
 * REL-069 adds a risk-adjusted metrics ranking chart and a real return-correlation heatmap. */
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
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card eyebrow="Ranked" title="Risk-Adjusted Metrics">
          <CompareMetricsChart rows={rows} />
        </Card>
        <Card eyebrow="Diversification" title="Return Correlation">
          <CorrelationMatrix ids={ids} />
        </Card>
      </div>
      <CompareEquityCurveChart rows={rows} />
    </div>
  );
}
