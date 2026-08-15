"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { CHART_COLOR_DOWN, CHART_COLOR_UP } from "@/lib/chart-theme";

/** REL-069: real pairwise correlation of daily equity-curve returns between the compared runs --
 * do two strategies tend to win and lose on the same days? A plain CSS-grid heatmap rather than
 * an echarts chart, matching this codebase's precedent of hand-built visuals (Portfolio & Risk's
 * gauges) for cases a generic chart type doesn't fit well. A `null` cell (rendered `—`) means too
 * few real overlapping calendar days between that pair's real equity curves, never a fabricated
 * 0 -- the same honest-null convention every other real-data view in this app already follows. */
export function CorrelationMatrix({ ids }: { ids: string[] }) {
  const query = useQuery({
    queryKey: ["compare-backtests-correlation", ids],
    queryFn: () => api.compareBacktestsCorrelation(ids),
    enabled: ids.length >= 2,
  });

  if (query.isLoading) {
    return <div className="h-40 animate-pulse rounded-xl bg-bg" />;
  }
  const data = query.data;
  if (!data || data.run_ids.length < 2) {
    return (
      <p className="text-xs text-text-faint">
        Not enough of the selected runs have a real equity curve to compute correlation.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <div
        className="grid gap-1"
        style={{
          gridTemplateColumns: `120px repeat(${data.run_ids.length}, minmax(64px, 1fr))`,
        }}
      >
        <div />
        {data.run_labels.map((label, i) => (
          <div
            key={`col-${data.run_ids[i]}`}
            className="truncate px-1 text-center text-[9px] font-medium text-text-faint"
            title={label}
          >
            {label}
          </div>
        ))}
        {data.run_labels.map((rowLabel, ri) => (
          <div key={`row-${data.run_ids[ri]}`} className="contents">
            <div className="truncate pr-2 text-[10px] font-medium text-text-faint" title={rowLabel}>
              {rowLabel}
            </div>
            {data.matrix[ri].map((value, ci) => (
              <div
                key={`cell-${data.run_ids[ri]}-${data.run_ids[ci]}`}
                className={cn(
                  "flex items-center justify-center rounded-md py-2 font-mono-tabular text-[10px] font-semibold",
                  value === null && "border border-dashed border-card-edge text-text-faint",
                )}
                style={value !== null ? { backgroundColor: correlationColor(value) } : undefined}
                title={
                  value === null
                    ? "Fewer than 10 real overlapping calendar days between these two runs."
                    : `Correlation: ${value.toFixed(2)}`
                }
              >
                {value === null ? "—" : value.toFixed(2)}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

/** Diverging scale: strong negative -> CHART_COLOR_DOWN, strong positive -> CHART_COLOR_UP,
 * near-zero -> transparent (lets the card background show through, reading as "no signal"). */
function correlationColor(value: number): string {
  const magnitude = Math.min(1, Math.abs(value));
  const base = value >= 0 ? CHART_COLOR_UP : CHART_COLOR_DOWN;
  const alpha = 0.12 + magnitude * 0.55;
  const { r, g, b } = hexToRgb(base);
  return `rgba(${r}, ${g}, ${b}, ${alpha.toFixed(2)})`;
}

function hexToRgb(hex: string): { r: number; g: number; b: number } {
  const n = parseInt(hex.slice(1), 16);
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
}
