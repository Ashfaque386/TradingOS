"use client";

import ReactECharts from "echarts-for-react";
import { useThemeStore } from "@/lib/theme-store";
import { getChartColors } from "@/lib/chart-theme";
import { METRICS } from "./metric-grid";
import type { BacktestCompareRow } from "@/lib/api";

const SERIES_COLORS = ["#ff5c7a", "#c94bff", "#10b981", "#f59e0b", "#38bdf8", "#f472b6"];

// The 6 real "higher is better" risk-adjusted metrics -- Max DD/Expectancy/Trades/MC p95 DD are
// deliberately left out of this view, either because they're not a "bigger is better" figure
// (drawdown) or don't share a comparable relative scale with the rest (expectancy is ₹, trades
// is a count). The full set is still always visible in BacktestComparisonTable above this chart.
const COMPARE_METRIC_KEYS: (keyof BacktestCompareRow)[] = [
  "sharpe_ratio",
  "sortino_ratio",
  "calmar_ratio",
  "win_rate",
  "profit_factor",
  "cagr",
];

/** REL-069: each metric has its own scale (Sharpe ~0-3, Win Rate 0-1, CAGR can exceed 1), so
 * mixing them on one shared axis would be misleading -- each metric's bars are instead
 * normalized to that metric's own largest real magnitude among the compared runs (a run at 100%
 * has the best real value for that one metric; the tooltip always shows the real, unnormalized
 * number via METRICS' own formatter). Reuses metric-grid.tsx's `METRICS` as the single source of
 * truth for labels/formatters rather than re-declaring them. */
export function CompareMetricsChart({ rows }: { rows: BacktestCompareRow[] }) {
  const mode = useThemeStore((s) => s.mode);
  const colors = getChartColors(mode);

  const metrics = METRICS.filter((m) => COMPARE_METRIC_KEYS.includes(m.key));
  const rawValues: number[][] = rows.map((row) =>
    metrics.map((m) => {
      const raw = row[m.key];
      return typeof raw === "number" ? raw : 0;
    }),
  );
  const perMetricMaxAbs = metrics.map((_, mi) =>
    Math.max(1e-9, ...rawValues.map((vals) => Math.abs(vals[mi]))),
  );

  const series = rows.map((row, ri) => ({
    name: `${row.strategy_name} · ${new Date(row.created_at).toLocaleDateString("en-IN")}`,
    type: "bar",
    itemStyle: { color: SERIES_COLORS[ri % SERIES_COLORS.length] },
    data: rawValues[ri].map((v, mi) => Number(((v / perMetricMaxAbs[mi]) * 100).toFixed(1))),
  }));

  const option = {
    grid: { left: 90, right: 24, top: 32, bottom: 16 },
    xAxis: {
      type: "value",
      max: 100,
      min: (value: { min: number }) => Math.min(0, Math.floor(value.min / 20) * 20),
      axisLine: { show: false },
      splitLine: { lineStyle: { color: colors.splitLine } },
      axisLabel: { color: colors.textFaint, fontSize: 9, formatter: "{value}%" },
    },
    yAxis: {
      type: "category",
      data: metrics.map((m) => m.label),
      axisLine: { lineStyle: { color: colors.axisLine } },
      axisLabel: { color: colors.textDim, fontSize: 10 },
    },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      backgroundColor: colors.panel,
      borderColor: colors.grid,
      textStyle: { color: colors.text, fontFamily: "var(--font-sans)", fontSize: 11 },
      formatter: (params: { seriesIndex: number; dataIndex: number; seriesName: string }[]) =>
        params
          .map((p) => {
            const raw = rawValues[p.seriesIndex][p.dataIndex];
            return `${p.seriesName}: ${metrics[p.dataIndex].fmt(raw)}`;
          })
          .join("<br/>"),
    },
    legend: {
      data: series.map((s) => s.name),
      textStyle: { color: colors.textDim, fontSize: 9 },
      top: 0,
      type: "scroll",
    },
    series,
  };

  return (
    <div>
      <p className="mb-2 text-[10px] text-text-faint">
        Each metric is scaled to its own largest real value among the compared runs (100% = best
        for that metric) — hover a bar for the real number.
      </p>
      <ReactECharts
        option={option}
        style={{ height: Math.max(220, metrics.length * 44) }}
        opts={{ renderer: "svg" }}
      />
    </div>
  );
}
