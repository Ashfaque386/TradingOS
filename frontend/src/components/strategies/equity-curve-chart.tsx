"use client";

import ReactECharts from "echarts-for-react";
import { useThemeStore } from "@/lib/theme-store";
import { getChartColors } from "@/lib/chart-theme";
import type { EquityCurvePoint, OhlcvBar, TradeSummary } from "@/lib/api";

/** REL-044/046: moved here (was a module-local, unexported helper inside
 * app/(app)/backtests/page.tsx) so both that page and review-panel.tsx can share one
 * implementation of "index a real benchmark series to 100 at the strategy's own start date"
 * instead of duplicating it. */
export function buildBenchmarkOverlay(
  points: { date: string }[],
  benchmarkBars: OhlcvBar[],
): (number | null)[] | undefined {
  if (points.length === 0 || benchmarkBars.length === 0) return undefined;
  const byDate = new Map(benchmarkBars.map((b) => [b.date, b.close]));
  const firstMatch = points.find((p) => byDate.has(p.date));
  if (!firstMatch) return undefined;
  const base = byDate.get(firstMatch.date)!;
  return points.map((p) => {
    const close = byDate.get(p.date);
    return close !== undefined ? (close / base) * 100 : null;
  });
}

/** Equity curve vs Nifty 50. REL-017 E17.3: `benchmark` is real ^NSEI OHLCV (ingested by
 * REL-016's E16.2, src/data/ingest/pipeline.py --source yfinance --symbols ^NSEI), filtered by
 * the caller to the backtest's own date range and passed in already-aligned to `points` by
 * date -- both series are normalized to start at 100 here so they're comparable regardless of
 * the strategy's actual capital base vs. the index's own price level. `benchmark` is optional
 * and omitted (not fabricated as a flat line) whenever the caller has no overlapping real data
 * for the period.
 *
 * REL-043: `trades` is optional and purely additive -- a `scatter` series marking each real
 * trade's entry/exit date on the existing `category` xAxis, layered on top of the untouched
 * `line`/`benchmark` series above. review-panel.tsx renders this component without ever passing
 * `trades`, so that usage is byte-for-byte unaffected. */
export function EquityCurveChart({
  points,
  benchmark,
  trades,
}: {
  points: EquityCurvePoint[];
  benchmark?: (number | null)[];
  trades?: TradeSummary[];
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
  if (trades && trades.length > 0) {
    const indexByDate = new Map(points.map((p, i) => [p.date, i]));
    const markerAt = (date: string, value: number) => {
      const i = indexByDate.get(date);
      return i === undefined ? null : [i, normalizedEquity[i], value];
    };
    const entryMarkers = trades
      .map((t) => markerAt(t.entry_date, t.pnl))
      .filter((m): m is [number, number, number] => m !== null);
    const exitMarkers = trades
      .map((t) => markerAt(t.exit_date, t.pnl))
      .filter((m): m is [number, number, number] => m !== null);
    if (entryMarkers.length > 0) {
      series.push({
        name: "Entry",
        type: "scatter",
        data: entryMarkers,
        symbol: "triangle",
        symbolSize: 7,
        itemStyle: { color: colors.textDim },
      });
    }
    if (exitMarkers.length > 0) {
      series.push({
        name: "Exit (PnL)",
        type: "scatter",
        data: exitMarkers,
        symbol: "diamond",
        symbolSize: 7,
        itemStyle: {
          color: (params: { data: [number, number, number] }) =>
            params.data[2] >= 0 ? "#10b981" : "#f43f5e",
        },
      });
    }
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
    legend:
      series.length > 1
        ? {
            data: series.map((s) => s.name as string),
            textStyle: { color: colors.textDim, fontSize: 10 },
            top: 0,
          }
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
