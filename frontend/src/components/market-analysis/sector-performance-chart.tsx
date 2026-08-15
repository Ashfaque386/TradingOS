"use client";

import ReactECharts from "echarts-for-react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useThemeStore } from "@/lib/theme-store";
import { CHART_COLOR_DOWN, CHART_COLOR_UP, getChartColors } from "@/lib/chart-theme";
import { Card } from "@/components/ui/card";

/** REL-067: real NSE sector-index day-change, via GET /market/pulse -- the same 4 real yfinance-
 * backed tickers (^CNXIT/^NSEBANK/^CNXAUTO/^CNXPHARMA) the Market Analyst Agent's own
 * NseSectorDataSkill already fetches. Index-level performance, not a per-position portfolio
 * sector breakdown -- that's a separate, still-unbuilt capability (needs a symbol→sector
 * constituent mapping this app doesn't have; see ExposureDonut's own "By Sector" tab). */
export function SectorPerformanceChart() {
  const pulseQuery = useQuery({
    queryKey: ["market-pulse"],
    queryFn: api.marketPulse,
    refetchInterval: 60_000,
  });
  const mode = useThemeStore((s) => s.mode);
  const colors = getChartColors(mode);

  const sectors = pulseQuery.data?.sectors ?? [];
  const sorted = [...sectors].sort((a, b) => b.change_pct - a.change_pct);

  return (
    <Card eyebrow="Real NSE Sector Indices" title="Sector Performance">
      {pulseQuery.isLoading ? (
        <div className="h-[220px] animate-pulse rounded-xl bg-bg" />
      ) : sorted.length === 0 ? (
        <div className="flex h-[220px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-card-edge text-center">
          <p className="max-w-[220px] text-xs text-text-faint">
            No real sector-index data available right now — Yahoo Finance returned nothing for
            any tracked sector ticker on the last request.
          </p>
        </div>
      ) : (
        <ReactECharts
          style={{ height: 220 }}
          opts={{ renderer: "svg" }}
          option={{
            grid: { left: 60, right: 24, top: 8, bottom: 8 },
            tooltip: {
              trigger: "item",
              backgroundColor: colors.panel,
              borderColor: colors.grid,
              textStyle: { color: colors.text, fontFamily: "var(--font-sans)" },
              formatter: (p: { name: string; value: number }) =>
                `${p.name}<br/>${p.value > 0 ? "+" : ""}${p.value.toFixed(2)}%`,
            },
            xAxis: {
              type: "value",
              axisLine: { lineStyle: { color: colors.axisLine } },
              splitLine: { lineStyle: { color: colors.splitLine } },
              axisLabel: { color: colors.textFaint, formatter: "{value}%" },
            },
            yAxis: {
              type: "category",
              data: sorted.map((s) => s.name),
              axisLine: { lineStyle: { color: colors.axisLine } },
              axisLabel: { color: colors.textDim, fontFamily: "var(--font-sans)" },
            },
            series: [
              {
                type: "bar",
                barWidth: "55%",
                data: sorted.map((s) => ({
                  value: Number(s.change_pct.toFixed(2)),
                  itemStyle: {
                    color: s.change_pct >= 0 ? CHART_COLOR_UP : CHART_COLOR_DOWN,
                    borderRadius: s.change_pct >= 0 ? [0, 4, 4, 0] : [4, 0, 0, 4],
                  },
                })),
              },
            ],
          }}
        />
      )}
    </Card>
  );
}
