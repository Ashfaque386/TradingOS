"use client";

import type { StrategySummary } from "@/lib/api";

/** REL-040/041: `backtest_count` closes the exact confusion the user reported -- the dashboard
 * used to show an empty state for whichever strategy loaded first with no cue that other
 * strategies actually had history to look at. */
export function StrategyPicker({
  strategies,
  value,
  onChange,
  isLoading,
}: {
  strategies: StrategySummary[];
  value: string | null;
  onChange: (id: string) => void;
  isLoading: boolean;
}) {
  if (isLoading) {
    return <div className="h-9 animate-pulse rounded-lg bg-bg" />;
  }
  if (strategies.length === 0) {
    return <p className="text-xs text-text-faint">No strategies exist yet.</p>;
  }
  return (
    <select
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value)}
      className="rounded-md border border-card-edge bg-bg px-2.5 py-1.5 text-xs text-text"
    >
      {strategies.map((s) => (
        <option key={s.id} value={s.id}>
          {s.name} ({s.status}) · {s.backtest_count} {s.backtest_count === 1 ? "run" : "runs"}
        </option>
      ))}
    </select>
  );
}
