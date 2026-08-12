"use client";

import ReactECharts from "echarts-for-react";
import { useThemeStore } from "@/lib/theme-store";
import { getChartColors } from "@/lib/chart-theme";
import type { BacktestCompareRow } from "@/lib/api";

const SERIES_COLORS = ["#ff5c7a", "#c94bff", "#10b981", "#f59e0b", "#38bdf8", "#f472b6"];

/**
 * REL-042: a real overlay of 2-6 arbitrary backtest runs, each indexed to 100 at its own start so
 * runs are comparable regardless of capital base -- deliberately a NEW component, not an
 * extension of components/strategies/equity-curve-chart.tsx. That component's xAxis is a single
 * shared `category` array (`points.map(p => p.date)`) that every series implicitly shares; runs
 * being compared here can have entirely different date ranges (different strategies, different
 * backtest windows), so this uses ECharts' `time`-typed xAxis with each series carrying its own
 * `[timestamp, value]` tuples instead. Kept separate specifically so review-panel.tsx (which also
 * renders the original EquityCurveChart) is never at risk from this change.
 */
export function CompareEquityCurveChart({ rows }: { rows: BacktestCompareRow[] }) {
  const mode = useThemeStore((s) => s.mode);
  const colors = getChartColors(mode);

  const withCurves = rows.filter((r) => r.equity_curve.length > 0);
  if (withCurves.length === 0) {
    return (
      <div className="flex h-[260px] items-center justify-center rounded-xl border border-dashed border-card-edge">
        <p className="text-xs text-text-faint">
          None of the selected runs have a real equity curve to overlay.
        </p>
      </div>
    );
  }

  const series = withCurves.map((row, i) => {
    const base = row.equity_curve[0].equity;
    return {
      name: `${row.strategy_name} · ${new Date(row.created_at).toLocaleDateString("en-IN")}`,
      type: "line",
      showSymbol: false,
      lineStyle: { color: SERIES_COLORS[i % SERIES_COLORS.length], width: 2 },
      data: row.equity_curve.map((p) => [p.date, base !== 0 ? (p.equity / base) * 100 : 100]),
    };
  });

  const option = {
    grid: { left: 48, right: 16, top: 32, bottom: 28 },
    xAxis: {
      type: "time",
      axisLine: { lineStyle: { color: colors.axisLine } },
      axisLabel: { color: colors.textFaint, fontSize: 10 },
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
      <ReactECharts option={option} style={{ height: 260 }} opts={{ renderer: "svg" }} />
      {withCurves.length < rows.length && (
        <p className="mt-2 text-[10px] text-text-faint">
          {rows.length - withCurves.length} of {rows.length} selected runs have no real equity
          curve and are omitted from the overlay above.
        </p>
      )}
    </div>
  );
}
