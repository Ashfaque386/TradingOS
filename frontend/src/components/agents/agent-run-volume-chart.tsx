"use client";

import ReactECharts from "echarts-for-react";
import { useThemeStore } from "@/lib/theme-store";
import { CHART_COLOR_DOWN, CHART_COLOR_UP, getChartColors } from "@/lib/chart-theme";
import type { AgentAnalyticsTrendPoint } from "@/lib/api";

/** REL-068: real daily run-volume trend (GET /agents/analytics/trend), completed vs. failed
 * stacked per day -- only real days with at least 1 run appear on the axis, never a
 * zero-filled synthetic day standing in for a real gap in the ledger. */
export function AgentRunVolumeChart({ points }: { points: AgentAnalyticsTrendPoint[] }) {
  const mode = useThemeStore((s) => s.mode);
  const colors = getChartColors(mode);

  if (points.length === 0) {
    return (
      <div className="flex h-[180px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-card-edge text-center">
        <p className="max-w-[220px] text-xs text-text-faint">
          No agent runs in this window yet — the trend fills in as soon as a research cycle runs.
        </p>
      </div>
    );
  }

  return (
    <ReactECharts
      style={{ height: 180 }}
      opts={{ renderer: "svg" }}
      option={{
        grid: { left: 40, right: 16, top: 24, bottom: 28 },
        legend: {
          data: ["Completed", "Failed"],
          top: 0,
          right: 0,
          textStyle: { color: colors.textFaint, fontSize: 10, fontFamily: "var(--font-sans)" },
          itemWidth: 10,
          itemHeight: 10,
        },
        xAxis: {
          type: "category",
          data: points.map((p) => p.date),
          axisLine: { lineStyle: { color: colors.axisLine } },
          axisLabel: { color: colors.textFaint, fontSize: 10, formatter: (v: string) => v.slice(5) },
          splitLine: { show: false },
        },
        yAxis: {
          type: "value",
          minInterval: 1,
          axisLine: { show: false },
          splitLine: { lineStyle: { color: colors.splitLine } },
          axisLabel: { color: colors.textFaint, fontSize: 10 },
        },
        tooltip: {
          trigger: "axis",
          backgroundColor: colors.panel,
          borderColor: colors.grid,
          textStyle: { color: colors.text, fontFamily: "var(--font-sans)", fontSize: 11 },
        },
        series: [
          {
            name: "Completed",
            type: "bar",
            stack: "runs",
            data: points.map((p) => p.completed),
            itemStyle: { color: CHART_COLOR_UP },
          },
          {
            name: "Failed",
            type: "bar",
            stack: "runs",
            data: points.map((p) => p.failed),
            itemStyle: { color: CHART_COLOR_DOWN },
          },
        ],
      }}
    />
  );
}
