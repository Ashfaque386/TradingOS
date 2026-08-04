"use client";

import { cn } from "@/lib/utils";
import type { ShadowModeStatus } from "@/lib/api";

const GATE_TARGET_DAYS = 5;

export function ShadowModePanel({ status }: { status: ShadowModeStatus | undefined }) {
  if (!status) {
    return <div className="h-40 animate-pulse rounded-xl bg-bg" />;
  }

  const days = [...status.daily_summary].reverse().slice(0, 10);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-4">
        <div>
          <div className="font-mono-tabular text-3xl font-semibold text-text">
            {status.consecutive_clean_days}
            <span className="ml-1 text-sm font-normal text-text-faint">
              / {GATE_TARGET_DAYS} clean days
            </span>
          </div>
          <p className="text-[11px] text-text-faint">
            Consecutive days with at least one broker-validation attempt and zero errors.
          </p>
        </div>
        <span
          className={cn(
            "ml-auto flex-shrink-0 rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider",
            status.go_live_gate_met
              ? "bg-up/10 text-up"
              : "bg-bg text-text-faint",
          )}
        >
          {status.go_live_gate_met ? "Streak cleared" : "In progress"}
        </span>
      </div>

      {days.length === 0 ? (
        <p className="text-xs text-text-faint">
          No Shadow Mode attempts recorded yet — run <code className="text-text-dim">scripts/run_daily_shadow_mode.py</code> to start the streak.
        </p>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {days.map((d) => (
            <div
              key={d.date}
              title={`${d.date}: ${d.attempts} attempt(s), ${d.errors} error(s)`}
              className={cn(
                "flex h-10 w-10 flex-col items-center justify-center rounded-lg text-[10px] font-medium",
                d.clean ? "bg-up/10 text-up" : "bg-down/10 text-down",
              )}
            >
              <span>{d.attempts}</span>
              <span className="text-[8px] uppercase tracking-wider opacity-70">
                {d.errors > 0 ? `${d.errors} err` : "clean"}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
