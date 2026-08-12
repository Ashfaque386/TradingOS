"use client";

import { useQuery } from "@tanstack/react-query";
import ReactECharts from "echarts-for-react";
import { useThemeStore } from "@/lib/theme-store";
import { getChartColors } from "@/lib/chart-theme";
import { api } from "@/lib/api";

/**
 * REL-042: visualizes the full Monte Carlo max-drawdown distribution -- previously only the
 * single P95 scalar (BacktestSummary.monte_carlo_p95_max_drawdown) was ever shown anywhere.
 * GET .../monte-carlo (REL-040) recomputes this live from the real persisted trade ledger every
 * time this component mounts (cheap, milliseconds) rather than persisting the full distribution,
 * so re-opening this tab always reflects a fresh resample, not a stale cached one.
 */
export function MonteCarloHistogram({ backtestId }: { backtestId: string }) {
  const mode = useThemeStore((s) => s.mode);
  const colors = getChartColors(mode);

  const query = useQuery({
    queryKey: ["monte-carlo-histogram", backtestId],
    queryFn: () => api.monteCarloHistogram(backtestId),
    retry: false,
  });

  if (query.isLoading) {
    return <div className="h-[220px] animate-pulse rounded-xl bg-bg" />;
  }

  if (query.isError) {
    return (
      <p className="text-[11px] leading-relaxed text-text-faint">
        Not enough real closed trades (fewer than 2) in this backtest&apos;s window to run a Monte
        Carlo simulation.
      </p>
    );
  }

  const mc = query.data!;
  const bucketLabels = mc.bucket_edges
    .slice(0, -1)
    .map((edge, i) => `${(edge * 100).toFixed(1)}% to ${(mc.bucket_edges[i + 1] * 100).toFixed(1)}%`);

  const option = {
    grid: { left: 48, right: 16, top: 16, bottom: 40 },
    xAxis: {
      type: "category",
      data: bucketLabels,
      axisLine: { lineStyle: { color: colors.axisLine } },
      axisLabel: { color: colors.textFaint, fontSize: 9, rotate: 45, interval: 4 },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      axisLine: { show: false },
      splitLine: { lineStyle: { color: colors.splitLine } },
      axisLabel: { color: colors.textFaint, fontSize: 10 },
      name: "Simulated runs",
      nameTextStyle: { color: colors.textFaint, fontSize: 9 },
    },
    tooltip: {
      trigger: "axis",
      backgroundColor: colors.panel,
      borderColor: colors.grid,
      textStyle: { color: colors.text, fontFamily: "var(--font-sans)", fontSize: 11 },
    },
    series: [
      {
        name: "Simulated max drawdown",
        type: "bar",
        data: mc.bucket_counts,
        itemStyle: { color: "rgba(255,92,122,0.55)" },
        markLine: {
          symbol: "none",
          label: { color: colors.text, fontSize: 9 },
          lineStyle: { color: "#f59e0b", type: "dashed", width: 1.5 },
          data: [
            {
              xAxis: nearestBucketIndex(mc.bucket_edges, mc.percentile_95_max_drawdown),
              label: { formatter: `P95: ${(mc.percentile_95_max_drawdown * 100).toFixed(1)}%` },
            },
            {
              xAxis: nearestBucketIndex(mc.bucket_edges, mc.historical_max_drawdown),
              label: { formatter: `Historical: ${(mc.historical_max_drawdown * 100).toFixed(1)}%` },
              lineStyle: { color: "#f43f5e", type: "dashed", width: 1.5 },
            },
          ],
        },
      },
    ],
  };

  return (
    <div>
      <p className="mb-2 text-[11px] text-text-faint">
        {mc.n_simulations.toLocaleString("en-IN")} resamples of this backtest&apos;s real
        per-trade returns.
      </p>
      <ReactECharts option={option} style={{ height: 260 }} opts={{ renderer: "svg" }} />
    </div>
  );
}

function nearestBucketIndex(edges: number[], value: number): number {
  let closest = 0;
  let closestDist = Infinity;
  for (let i = 0; i < edges.length - 1; i++) {
    const mid = (edges[i] + edges[i + 1]) / 2;
    const dist = Math.abs(mid - value);
    if (dist < closestDist) {
      closestDist = dist;
      closest = i;
    }
  }
  return closest;
}
