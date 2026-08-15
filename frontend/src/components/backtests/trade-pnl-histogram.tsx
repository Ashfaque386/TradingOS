"use client";

import ReactECharts from "echarts-for-react";
import { useThemeStore } from "@/lib/theme-store";
import { CHART_COLOR_DOWN, CHART_COLOR_UP, getChartColors } from "@/lib/chart-theme";
import type { TradeSummary } from "@/lib/api";

const BUCKET_COUNT = 16;

/** REL-069: distribution of this backtest's real per-trade returns (TradeSummary.return_pct,
 * already fetched by the page for the Trade List tab -- no new endpoint) -- shows the real shape
 * behind the single win_rate/expectancy scalars in the metrics grid: is it many small wins and a
 * few large losses, or the reverse? Bucketed client-side since the full trade list is already in
 * memory and this is a one-time histogram of a bounded (per-backtest) trade count. */
export function TradePnlHistogram({ trades }: { trades: TradeSummary[] | undefined }) {
  const mode = useThemeStore((s) => s.mode);
  const colors = getChartColors(mode);

  if (!trades || trades.length < 2) {
    return (
      <p className="text-[11px] leading-relaxed text-text-faint">
        Not enough real closed trades (fewer than 2) in this backtest to plot a distribution.
      </p>
    );
  }

  const returns = trades.map((t) => t.return_pct);
  const min = Math.min(...returns);
  const max = Math.max(...returns);
  const span = max - min || 1;
  const bucketWidth = span / BUCKET_COUNT;
  const counts = new Array(BUCKET_COUNT).fill(0);
  for (const r of returns) {
    const idx = Math.min(BUCKET_COUNT - 1, Math.floor((r - min) / bucketWidth));
    counts[idx] += 1;
  }
  const bucketLabels = Array.from({ length: BUCKET_COUNT }, (_, i) => {
    const lo = min + i * bucketWidth;
    const hi = lo + bucketWidth;
    return `${(lo * 100).toFixed(1)}% to ${(hi * 100).toFixed(1)}%`;
  });
  const barColors = Array.from({ length: BUCKET_COUNT }, (_, i) => {
    const midpoint = min + (i + 0.5) * bucketWidth;
    return midpoint >= 0 ? CHART_COLOR_UP : CHART_COLOR_DOWN;
  });

  const option = {
    grid: { left: 48, right: 16, top: 16, bottom: 44 },
    xAxis: {
      type: "category",
      data: bucketLabels,
      axisLine: { lineStyle: { color: colors.axisLine } },
      axisLabel: { color: colors.textFaint, fontSize: 9, rotate: 45, interval: 1 },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      minInterval: 1,
      axisLine: { show: false },
      splitLine: { lineStyle: { color: colors.splitLine } },
      axisLabel: { color: colors.textFaint, fontSize: 10 },
      name: "Trades",
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
        name: "Trades",
        type: "bar",
        data: counts.map((c, i) => ({ value: c, itemStyle: { color: barColors[i] } })),
      },
    ],
  };

  return (
    <div>
      <p className="mb-2 text-[11px] text-text-faint">
        Distribution of {returns.length} real per-trade returns, bucketed by outcome.
      </p>
      <ReactECharts option={option} style={{ height: 260 }} opts={{ renderer: "svg" }} />
    </div>
  );
}
