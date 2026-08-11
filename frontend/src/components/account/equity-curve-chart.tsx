"use client";

import { formatCompactINR } from "@/lib/utils";
import type { EquityCurvePoint } from "@/lib/api";

/** REL-034: a small, self-contained SVG line chart -- the account's real equity history is a
 * single series over time, not the multi-pane candlestick/volume view `candlestick-chart.tsx`
 * (TradingView lightweight-charts) already owns, so this doesn't pull that heavier dependency in
 * for a shape it isn't built for. */
export function EquityCurveChart({ points }: { points: EquityCurvePoint[] }) {
  if (points.length < 2) {
    return (
      <div className="flex h-[220px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-card-edge text-center">
        <p className="text-xs text-text-faint">
          Not enough history yet — the equity curve fills in as real trading days pass.
        </p>
      </div>
    );
  }

  const width = 640;
  const height = 200;
  const padding = 8;

  const values = points.map((p) => p.equity);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  const stepX = (width - padding * 2) / (points.length - 1);
  const coords = points.map((p, i) => {
    const x = padding + i * stepX;
    const y = padding + (1 - (p.equity - min) / range) * (height - padding * 2);
    return { x, y, point: p };
  });

  const linePath = coords.map((c, i) => `${i === 0 ? "M" : "L"}${c.x},${c.y}`).join(" ");
  const areaPath = `${linePath} L${coords[coords.length - 1].x},${height - padding} L${coords[0].x},${height - padding} Z`;

  const last = points[points.length - 1];
  const first = points[0];
  const positive = last.equity >= first.equity;

  return (
    <div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full"
        preserveAspectRatio="none"
        role="img"
        aria-label="Account equity over time"
      >
        <defs>
          <linearGradient id="equity-curve-fill" x1="0" y1="0" x2="0" y2="1">
            <stop
              offset="0%"
              stopColor={positive ? "var(--color-up)" : "var(--color-down)"}
              stopOpacity="0.25"
            />
            <stop
              offset="100%"
              stopColor={positive ? "var(--color-up)" : "var(--color-down)"}
              stopOpacity="0"
            />
          </linearGradient>
        </defs>
        <path d={areaPath} fill="url(#equity-curve-fill)" stroke="none" />
        <path
          d={linePath}
          fill="none"
          stroke={positive ? "var(--color-up)" : "var(--color-down)"}
          strokeWidth="2"
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        <circle
          cx={coords[coords.length - 1].x}
          cy={coords[coords.length - 1].y}
          r="3.5"
          fill={positive ? "var(--color-up)" : "var(--color-down)"}
        />
      </svg>
      <div className="mt-2 flex items-center justify-between text-[11px] text-text-faint">
        <span>{new Date(first.snapshot_date).toLocaleDateString("en-IN")}</span>
        <span className="font-mono-tabular">{formatCompactINR(last.equity)}</span>
        <span>{new Date(last.snapshot_date).toLocaleDateString("en-IN")}</span>
      </div>
    </div>
  );
}
