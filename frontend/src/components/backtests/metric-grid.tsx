"use client";

import { cn } from "@/lib/utils";
import type { BacktestSummary } from "@/lib/api";

export const METRICS: {
  key: keyof BacktestSummary;
  label: string;
  fmt: (v: number) => string;
  /** Only set for metrics with an unambiguous, standard good/bad threshold -- avoids guessing at
   * a sign convention (e.g. drawdown) that isn't worth risking a wrong-direction color cue on. */
  tone?: (v: number) => "up" | "warn" | "down";
}[] = [
  {
    key: "sharpe_ratio",
    label: "Sharpe",
    fmt: (v) => v.toFixed(2),
    tone: (v) => (v >= 1 ? "up" : v >= 0 ? "warn" : "down"),
  },
  { key: "sortino_ratio", label: "Sortino", fmt: (v) => v.toFixed(2) },
  { key: "calmar_ratio", label: "Calmar", fmt: (v) => v.toFixed(2) },
  { key: "max_drawdown", label: "Max DD", fmt: (v) => `${(v * 100).toFixed(1)}%` },
  { key: "cagr", label: "CAGR", fmt: (v) => `${(v * 100).toFixed(1)}%` },
  {
    key: "win_rate",
    label: "Win Rate",
    fmt: (v) => `${(v * 100).toFixed(0)}%`,
    tone: (v) => (v >= 0.5 ? "up" : v >= 0.4 ? "warn" : "down"),
  },
  { key: "profit_factor", label: "Profit Factor", fmt: (v) => v.toFixed(2) },
  { key: "expectancy", label: "Expectancy", fmt: (v) => `₹${v.toFixed(2)}` },
  { key: "total_trades", label: "Trades", fmt: (v) => v.toString() },
  {
    key: "monte_carlo_p95_max_drawdown",
    label: "MC p95 DD",
    fmt: (v) => `${(v * 100).toFixed(1)}%`,
  },
];

export const TONE_CLASS: Record<"up" | "warn" | "down", string> = {
  up: "text-up",
  warn: "text-warn",
  down: "text-down",
};

export function FullMetricGrid({ backtest }: { backtest: BacktestSummary }) {
  return (
    <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-5 lg:grid-cols-10">
      {METRICS.map(({ key, label, fmt, tone }) => {
        const raw = backtest[key];
        const isNum = typeof raw === "number";
        const toneClass = isNum && tone ? TONE_CLASS[tone(raw)] : "text-text";
        return (
          <div
            key={key}
            className="rounded-btn border border-card-edge bg-bg p-3 text-center transition-colors hover:border-text-faint/40"
          >
            <div className={cn("font-mono-tabular text-base font-semibold", toneClass)}>
              {isNum ? fmt(raw) : "—"}
            </div>
            <div className="mt-0.5 text-[9px] uppercase tracking-wider text-text-faint">{label}</div>
          </div>
        );
      })}
    </div>
  );
}
