"use client";

import ReactECharts from "echarts-for-react";
import { useThemeStore } from "@/lib/theme-store";
import { getChartColors } from "@/lib/chart-theme";
import type { EquityCurvePoint } from "@/lib/api";

/** Equity curve vs Nifty 50. REL-017 E17.3: `benchmark` is real ^NSEI OHLCV (ingested by
 * REL-016's E16.2, src/data/ingest/pipeline.py --source yfinance --symbols ^NSEI), filtered by
 * the caller to the backtest's own date range and passed in already-aligned to `points` by
 * date -- both series are normalized to start at 100 here so they're comparable regardless of
 * the strategy's actual capital base vs. the index's own price level. `benchmark` is optional
 * and omitted (not fabricated as a flat line) whenever the caller has no overlapping real data
 * for the period. */
export function EquityCurveChart({
  points,
  benchmark,
}: {
  points: EquityCurvePoint[];
  benchmark?: (number | null)[];
}) {
  const mode = useThemeStore((s) => s.mode);
  const colors = getChartColors(mode);

  if (points.length === 0) {
    return (
      <div className="flex h-[220px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-card-edge text-center">
        <p className="text-xs text-text-faint">No equity curve for this backtest.</p>
      </div>
    );
  }

  const baseEquity = points[0].equity;
  const normalizedEquity = points.map((p) => (baseEquity !== 0 ? (p.equity / baseEquity) * 100 : 100));

  const series: Record<string, unknown>[] = [
    {
      name: "Strategy",
      type: "line",
      data: normalizedEquity,
      showSymbol: false,
      lineStyle: { color: "#ff5c7a", width: 2 },
      areaStyle: { color: "rgba(255,92,122,0.08)" },
    },
  ];
  if (benchmark) {
    series.push({
      name: "Nifty 50",
      type: "line",
      data: benchmark,
      showSymbol: false,
      lineStyle: { color: "#c94bff", width: 1.5, type: "dashed" },
    });
  }

  const option = {
    grid: { left: 48, right: 16, top: 16, bottom: 28 },
    xAxis: {
      type: "category",
      data: points.map((p) => p.date),
      axisLine: { lineStyle: { color: colors.axisLine } },
      axisLabel: { color: colors.textFaint, fontSize: 10, formatter: (v: string) => v.slice(0, 7) },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      scale: true,
      axisLine: { show: false },
      splitLine: { lineStyle: { color: colors.splitLine } },
      axisLabel: { color: colors.textFaint, fontSize: 10, formatter: "{value}" },
      name: "Indexed to 100",
      nameTextStyle: { color: colors.textFaint, fontSize: 9 },
    },
    tooltip: {
      trigger: "axis",
      backgroundColor: colors.panel,
      borderColor: colors.grid,
      textStyle: { color: colors.text, fontFamily: "var(--font-sans)", fontSize: 11 },
    },
    legend: benchmark
      ? { data: ["Strategy", "Nifty 50"], textStyle: { color: colors.textDim, fontSize: 10 }, top: 0 }
      : undefined,
    series,
  };

  return (
    <div>
      <ReactECharts option={option} style={{ height: 220 }} opts={{ renderer: "svg" }} />
      {!benchmark && (
        <p className="mt-2 text-[10px] text-text-faint">
          No Nifty 50 overlay shown here — either this view doesn&apos;t fetch a benchmark
          series, or this run&apos;s dates have no overlapping real ^NSEI data in the lake. See
          the full Backtests dashboard for a benchmark-aware view.
        </p>
      )}
    </div>
  );
}
