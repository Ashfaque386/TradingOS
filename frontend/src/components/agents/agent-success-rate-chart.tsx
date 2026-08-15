"use client";

import ReactECharts from "echarts-for-react";
import { useThemeStore } from "@/lib/theme-store";
import { CHART_COLOR_DOWN, CHART_COLOR_UP, CHART_COLOR_WARN, getChartColors } from "@/lib/chart-theme";
import type { AgentAnalyticsSummaryRow } from "@/lib/api";

/** REL-068: real per-agent success-rate ranking (GET /agents/analytics/summary), for an
 * at-a-glance view of which agents are struggling -- only agents with at least one finished
 * (Completed or Failed) run are plotted, since a still-Running-only agent has no real success
 * rate to show yet. */
export function AgentSuccessRateChart({ rows }: { rows: AgentAnalyticsSummaryRow[] }) {
  const mode = useThemeStore((s) => s.mode);
  const colors = getChartColors(mode);

  const plottable = rows
    .filter((r) => r.success_rate !== null)
    .sort((a, b) => (a.success_rate ?? 0) - (b.success_rate ?? 0));

  if (plottable.length === 0) {
    return (
      <div className="flex h-[220px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-card-edge text-center">
        <p className="max-w-[220px] text-xs text-text-faint">
          No agent has a finished run in this window yet — nothing to rank.
        </p>
      </div>
    );
  }

  return (
    <ReactECharts
      style={{ height: Math.max(160, plottable.length * 28) }}
      opts={{ renderer: "svg" }}
      option={{
        grid: { left: 120, right: 40, top: 8, bottom: 8 },
        tooltip: {
          trigger: "item",
          backgroundColor: colors.panel,
          borderColor: colors.grid,
          textStyle: { color: colors.text, fontFamily: "var(--font-sans)" },
          formatter: (p: { name: string; value: number }) => `${p.name}<br/>${p.value.toFixed(0)}%`,
        },
        xAxis: {
          type: "value",
          min: 0,
          max: 100,
          axisLine: { lineStyle: { color: colors.axisLine } },
          splitLine: { lineStyle: { color: colors.splitLine } },
          axisLabel: { color: colors.textFaint, formatter: "{value}%" },
        },
        yAxis: {
          type: "category",
          data: plottable.map((r) => r.display_name),
          axisLine: { lineStyle: { color: colors.axisLine } },
          axisLabel: { color: colors.textDim, fontFamily: "var(--font-sans)" },
        },
        series: [
          {
            type: "bar",
            barWidth: "55%",
            data: plottable.map((r) => {
              const pct = (r.success_rate ?? 0) * 100;
              const color = pct >= 90 ? CHART_COLOR_UP : pct >= 60 ? CHART_COLOR_WARN : CHART_COLOR_DOWN;
              return { value: Number(pct.toFixed(1)), itemStyle: { color, borderRadius: [0, 4, 4, 0] } };
            }),
          },
        ],
      }}
    />
  );
}
