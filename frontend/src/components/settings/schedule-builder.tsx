"use client";

import { useEffect, useRef, useState } from "react";
import { Info } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  blankSelection,
  buildCron,
  DAY_LABELS,
  DAY_NAMES,
  MONTH_LABELS,
  parseCron,
  type CronSelection,
} from "@/lib/cron-schedule";

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

const MINUTES = Array.from({ length: 60 }, (_, i) => ({ value: i, label: pad2(i) }));
const HOURS = Array.from({ length: 24 }, (_, i) => ({ value: i, label: pad2(i) }));
const DAYS_OF_MONTH = Array.from({ length: 31 }, (_, i) => ({ value: i + 1, label: String(i + 1) }));
const MONTHS = MONTH_LABELS.map((label, i) => ({ value: i + 1, label }));

/** One scrollable multi-select column -- click a row to toggle it, no modifier key needed
 * (simpler than the reference's own "Ctrl + click" convention, same real capability: an empty
 * column means "every value"). Mirrors a real cron-trigger config screen the user pointed at
 * (Minutes/Hours/Days of month/Months/Days of week, each its own labeled scrollable list). */
function MultiSelectColumn<T extends string | number>({
  label,
  options,
  selected,
  onToggle,
  disabled,
}: {
  label: string;
  options: { value: T; label: string }[];
  selected: T[];
  onToggle: (value: T) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <span className="px-1.5 pb-1 text-[10px] font-medium uppercase tracking-wider text-text-faint">
        {label}
      </span>
      <div className="flex h-40 flex-col overflow-y-auto rounded-lg border border-card-edge bg-bg">
        {options.map((option) => {
          const active = selected.includes(option.value);
          return (
            <button
              key={option.value}
              type="button"
              disabled={disabled}
              onClick={() => onToggle(option.value)}
              aria-pressed={active}
              className={cn(
                "shrink-0 px-1.5 py-1 text-left font-mono-tabular text-[10px] transition-colors disabled:opacity-60",
                active
                  ? "bg-brand-via/15 font-semibold text-brand-via"
                  : "text-text-faint hover:bg-panel hover:text-text-dim",
              )}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/** REL-081 (follow-up, 2026-09-04): a real per-field multi-select schedule builder over
 * `src/lib/cron-schedule.ts`'s parse/build pair -- 5 scrollable columns (Minutes, Hours, Days of
 * month, Months, Days of week), each toggled independently, an empty column meaning "every
 * value" -- modeled directly on a real cron-trigger config screen the user pointed at twice
 * (replacing an earlier Hourly/Daily/Weekly/.../Custom tabbed version that wasn't it). No Years
 * column -- see cron-schedule.ts's own module docstring for why one would be fake here.
 *
 * A raw-cron fallback (toggled via the link below the columns) stays available for any real
 * expression the per-field model can't represent -- a step or a numeric range, this app's own
 * `scheduler_news_sentiment_cycle` ("every 30 minutes within the 9-15 hour range") included --
 * rather than ever silently
 * mis-editing something it can't represent structurally.
 *
 * Fully controlled: `value`/`onChange` carry the raw cron string, matching the parent's own
 * existing `cronDraft` state and dirty/validity checks exactly -- this only replaces the widget
 * used to edit that string, not the save/dirty/reset flow around it. */
export function ScheduleBuilder({
  value,
  onChange,
  disabled = false,
}: {
  value: string;
  onChange: (cron: string) => void;
  disabled?: boolean;
}) {
  const [selection, setSelection] = useState<CronSelection>(() => parseCron(value));
  // Tracks the last cron string *this component itself* emitted, so the effect below only
  // re-parses on a genuinely external change (e.g. the parent's "Reset to default" button) --
  // never on the round-trip of this component's own onChange, which would fight the user's
  // current selections mid-edit.
  const lastEmitted = useRef(value);

  useEffect(() => {
    if (value !== lastEmitted.current) {
      setSelection(parseCron(value));
      lastEmitted.current = value;
    }
  }, [value]);

  function update(next: CronSelection) {
    setSelection(next);
    const cron = buildCron(next);
    lastEmitted.current = cron;
    onChange(cron);
  }

  function toggle<K extends "minutes" | "hours" | "daysOfMonth" | "months">(
    key: K,
    val: number,
  ) {
    const current = selection[key];
    const next = current.includes(val)
      ? current.filter((v) => v !== val)
      : [...current, val];
    update({ ...selection, [key]: next });
  }

  function toggleDay(day: string) {
    const has = selection.daysOfWeek.includes(day);
    const daysOfWeek = has
      ? selection.daysOfWeek.filter((d) => d !== day)
      : [...selection.daysOfWeek, day];
    update({ ...selection, daysOfWeek });
  }

  if (selection.isCustom) {
    return (
      <div className="flex flex-col gap-1.5">
        <input
          value={selection.customCron}
          onChange={(e) => update({ ...selection, isCustom: true, customCron: e.target.value })}
          disabled={disabled}
          placeholder="M H DoM Mo DoW"
          className="rounded-md border border-card-edge bg-panel px-2 py-1.5 font-mono-tabular text-[11px] text-text disabled:opacity-60"
        />
        <span className="text-[10px] text-text-faint">
          This schedule uses cron syntax (a step or a range) the field picker below can&apos;t
          represent.
        </span>
        {!disabled && (
          <button
            type="button"
            onClick={() => update(blankSelection())}
            className="w-fit text-[10px] text-text-faint underline decoration-dotted hover:text-text-dim"
          >
            Switch to field picker (starts a new schedule)
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex gap-1.5">
        <MultiSelectColumn
          label="Minutes"
          options={MINUTES}
          selected={selection.minutes}
          onToggle={(v) => toggle("minutes", v)}
          disabled={disabled}
        />
        <MultiSelectColumn
          label="Hours"
          options={HOURS}
          selected={selection.hours}
          onToggle={(v) => toggle("hours", v)}
          disabled={disabled}
        />
        <MultiSelectColumn
          label="Day of month"
          options={DAYS_OF_MONTH}
          selected={selection.daysOfMonth}
          onToggle={(v) => toggle("daysOfMonth", v)}
          disabled={disabled}
        />
        <MultiSelectColumn
          label="Month"
          options={MONTHS}
          selected={selection.months}
          onToggle={(v) => toggle("months", v)}
          disabled={disabled}
        />
        <MultiSelectColumn
          label="Day of week"
          options={DAY_NAMES.map((d) => ({ value: d, label: DAY_LABELS[d] }))}
          selected={selection.daysOfWeek}
          onToggle={toggleDay}
          disabled={disabled}
        />
      </div>

      <p className="text-[10px] text-text-faint">
        An empty column means &quot;every value&quot;. If both Day of month and Day of week have
        selections, the schedule fires when either matches (real cron behavior).
      </p>

      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-[10px] text-text-faint">
          <Info className="h-3 w-3 shrink-0" />
          <span className="font-mono-tabular">{buildCron(selection)}</span>
          <span>· Asia/Kolkata</span>
        </div>
        {!disabled && (
          <button
            type="button"
            onClick={() => update({ ...selection, isCustom: true, customCron: buildCron(selection) })}
            className="shrink-0 text-[10px] text-text-faint underline decoration-dotted hover:text-text-dim"
          >
            Use raw cron instead
          </button>
        )}
      </div>
    </div>
  );
}
