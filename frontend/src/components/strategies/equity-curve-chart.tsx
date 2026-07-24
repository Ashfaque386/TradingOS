"use client";

import ReactECharts from "echarts-for-react";
import type { EquityCurvePoint } from "@/lib/api";

/** Equity curve vs Nifty 50, per Phase_7_Frontend_Architecture.md §2.3. Only the strategy's own
 * curve is real -- no Nifty 50 index data is ingested anywhere in the backend (confirmed; same
 * gap src/api/routers/portfolio.py already flags honestly for beta_vs_nifty50), so no benchmark
 * line is drawn rather than fabricating one. */
export function EquityCurveChart({ points }: { points: EquityCurvePoint[] }) {
  if (points.length === 0) {
    return (
      <div className="flex h-[220px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-white/10 text-center">
        <p className="text-xs text-zinc-500">No equity curve for this backtest.</p>
      </div>
    );
  }

  const option = {
    grid: { left: 48, right: 16, top: 16, bottom: 28 },
    xAxis: {
      type: "category",
      data: points.map((p) => p.date),
      axisLine: { lineStyle: { color: "rgba(255,255,255,0.15)" } },
      axisLabel: { color: "#71717a", fontSize: 10, formatter: (v: string) => v.slice(0, 7) },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      scale: true,
      axisLine: { show: false },
      splitLine: { lineStyle: { color: "rgba(255,255,255,0.06)" } },
      axisLabel: { color: "#71717a", fontSize: 10 },
    },
    tooltip: {
      trigger: "axis",
      backgroundColor: "rgba(24,24,27,0.95)",
      borderColor: "rgba(255,255,255,0.1)",
      textStyle: { color: "#f4f4f5", fontFamily: "var(--font-sans)", fontSize: 11 },
    },
    series: [
      {
        name: "Equity",
        type: "line",
        data: points.map((p) => p.equity),
        showSymbol: false,
        lineStyle: { color: "#22d3ee", width: 2 },
        areaStyle: { color: "rgba(34,211,238,0.08)" },
      },
    ],
  };

  return (
    <div>
      <ReactECharts option={option} style={{ height: 220 }} opts={{ renderer: "svg" }} />
      <p className="mt-2 text-[10px] text-zinc-600">
        No Nifty 50 benchmark line -- index data isn&apos;t ingested anywhere in the backend yet.
      </p>
    </div>
  );
}
