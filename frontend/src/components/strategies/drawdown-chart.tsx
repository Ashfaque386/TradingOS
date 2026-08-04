"use client";

import ReactECharts from "echarts-for-react";
import { useThemeStore } from "@/lib/theme-store";
import { getChartColors } from "@/lib/chart-theme";
import type { EquityCurvePoint } from "@/lib/api";

/** REL-017 E17.3: a real drawdown-from-running-peak chart computed client-side from the same
 * real equity curve EquityCurveChart already renders -- standard definition (current equity /
 * running peak equity - 1), not a separate backend endpoint, since the equity curve is the only
 * real data this needs and is already fetched. */
export function DrawdownChart({ points }: { points: EquityCurvePoint[] }) {
  const mode = useThemeStore((s) => s.mode);
  const colors = getChartColors(mode);

  if (points.length === 0) {
    return (
      <div className="flex h-[140px] items-center justify-center rounded-xl border border-dashed border-card-edge">
        <p className="text-xs text-text-faint">No equity curve for this backtest.</p>
      </div>
    );
  }

  const drawdownPct = points.reduce<{ peak: number; values: number[] }>(
    (acc, p) => {
      const peak = Math.max(acc.peak, p.equity);
      acc.values.push(peak !== 0 ? ((p.equity - peak) / peak) * 100 : 0);
      return { peak, values: acc.values };
    },
    { peak: points[0].equity, values: [] },
  ).values;

  const option = {
    grid: { left: 48, right: 16, top: 12, bottom: 28 },
    xAxis: {
      type: "category",
      data: points.map((p) => p.date),
      axisLine: { lineStyle: { color: colors.axisLine } },
      axisLabel: { color: colors.textFaint, fontSize: 10, formatter: (v: string) => v.slice(0, 7) },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      max: 0,
      axisLine: { show: false },
      splitLine: { lineStyle: { color: colors.splitLine } },
      axisLabel: { color: colors.textFaint, fontSize: 10, formatter: "{value}%" },
    },
    tooltip: {
      trigger: "axis",
      backgroundColor: colors.panel,
      borderColor: colors.grid,
      textStyle: { color: colors.text, fontFamily: "var(--font-sans)", fontSize: 11 },
      valueFormatter: (v: number) => `${v.toFixed(2)}%`,
    },
    series: [
      {
        name: "Drawdown",
        type: "line",
        data: drawdownPct,
        showSymbol: false,
        lineStyle: { color: "#f43f5e", width: 1.5 },
        areaStyle: { color: "rgba(244,63,94,0.12)" },
      },
    ],
  };

  return <ReactECharts option={option} style={{ height: 140 }} opts={{ renderer: "svg" }} />;
}
