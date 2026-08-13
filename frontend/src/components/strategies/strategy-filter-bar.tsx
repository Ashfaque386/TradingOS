"use client";

import { Search } from "lucide-react";
import { cn } from "@/lib/utils";
import type { StrategyStatus } from "@/lib/api";

export type AssetClassFilter = "All" | "Equity" | "F&O";
export type StyleFilter = "All" | "Intraday" | "Swing";

export const STAGE_OPTIONS: { status: StrategyStatus; label: string }[] = [
  { status: "Ideation", label: "Ideation" },
  { status: "Coding", label: "Coding" },
  { status: "Backtesting", label: "Backtesting" },
  { status: "PaperTrading", label: "Paper Trading" },
  { status: "Live", label: "Live" },
];

export interface StrategyFilterState {
  assetClass: AssetClassFilter;
  style: StyleFilter;
  stages: Set<StrategyStatus>;
  search: string;
}

export const DEFAULT_STRATEGY_FILTER_STATE: StrategyFilterState = {
  assetClass: "All",
  style: "All",
  stages: new Set(STAGE_OPTIONS.map((s) => s.status)),
  search: "",
};

function SegmentedGroup<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: T[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[10px] font-medium uppercase tracking-wider text-text-faint">
        {label}
      </span>
      <div
        className="inline-flex gap-0.5 rounded-lg border border-card-edge bg-bg p-0.5"
        role="group"
        aria-label={label}
      >
        {options.map((opt) => {
          const active = value === opt;
          return (
            <button
              key={opt}
              type="button"
              onClick={() => onChange(opt)}
              aria-pressed={active}
              className={cn(
                "rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors",
                active ? "bg-panel text-text shadow-card" : "text-text-faint hover:text-text-dim",
              )}
            >
              {opt}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/** REL-047: the direct fix for a Kanban board that only grows -- narrows the always-visible
 * 5-column, unfiltered list the user was navigating by scrolling. Modeled on the existing
 * Paper/Live/Both AccountScopeSwitcher's exact segmented-pill pattern
 * (components/layout/account-scope-switcher.tsx) so it reads as the same control vocabulary
 * rather than a new one-off widget. Purely client-side over the already-fetched strategies list
 * (matches KanbanBoard's own `byStatus` client-filter precedent) -- no new endpoint, the data
 * volume here has never justified server-side filtering. */
export function StrategyFilterBar({
  value,
  onChange,
}: {
  value: StrategyFilterState;
  onChange: (next: StrategyFilterState) => void;
}) {
  const toggleStage = (status: StrategyStatus) => {
    const next = new Set(value.stages);
    if (next.has(status)) {
      next.delete(status);
    } else {
      next.add(status);
    }
    onChange({ ...value, stages: next });
  };

  const allStagesOn = value.stages.size === STAGE_OPTIONS.length;

  return (
    <div className="mb-3 flex flex-wrap items-center gap-x-5 gap-y-2.5 rounded-2xl border border-card-edge bg-panel px-4 py-3">
      <div className="relative">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-faint" />
        <input
          type="text"
          value={value.search}
          onChange={(e) => onChange({ ...value, search: e.target.value })}
          placeholder="Search name or hypothesis…"
          aria-label="Search strategies"
          className="w-56 rounded-lg border border-card-edge bg-bg py-1.5 pl-8 pr-2.5 text-[11px] text-text placeholder:text-text-faint focus:outline-none focus:ring-1 focus:ring-brand-via/40"
        />
      </div>

      <SegmentedGroup
        label="Asset"
        options={["All", "Equity", "F&O"] as AssetClassFilter[]}
        value={value.assetClass}
        onChange={(assetClass) => onChange({ ...value, assetClass })}
      />

      <SegmentedGroup
        label="Style"
        options={["All", "Intraday", "Swing"] as StyleFilter[]}
        value={value.style}
        onChange={(style) => onChange({ ...value, style })}
      />

      <div className="flex items-center gap-1.5">
        <span className="text-[10px] font-medium uppercase tracking-wider text-text-faint">
          Stage
        </span>
        <div
          className="inline-flex flex-wrap gap-0.5 rounded-lg border border-card-edge bg-bg p-0.5"
          role="group"
          aria-label="Stage"
        >
          <button
            type="button"
            onClick={() =>
              onChange({
                ...value,
                stages: allStagesOn ? new Set() : new Set(STAGE_OPTIONS.map((s) => s.status)),
              })
            }
            aria-pressed={allStagesOn}
            className={cn(
              "rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors",
              allStagesOn
                ? "bg-panel text-text shadow-card"
                : "text-text-faint hover:text-text-dim",
            )}
          >
            All
          </button>
          {STAGE_OPTIONS.map(({ status, label }) => {
            const active = value.stages.has(status);
            return (
              <button
                key={status}
                type="button"
                onClick={() => toggleStage(status)}
                aria-pressed={active}
                className={cn(
                  "rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors",
                  active ? "bg-panel text-text shadow-card" : "text-text-faint hover:text-text-dim",
                )}
              >
                {label}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
