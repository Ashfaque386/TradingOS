/** REL-081 (follow-up, 2026-09-04): parses a real 5-field cron expression into a per-field
 * multi-select shape (which minutes, which hours, which days-of-month, which months, which
 * days-of-week are selected) and builds one back -- modeled directly on a real cron-trigger
 * config screen the user pointed at (Minutes/Hours/Days of month/Months/Days of week, each its
 * own scrollable multi-select list; "For multiple selection, press Ctrl + click"). An empty
 * selection in a field means "every value" (`*`), matching that same reference's own convention
 * and real cron semantics.
 *
 * Note: that reference screen also had a Years column. APScheduler's own `CronTrigger` supports
 * a 6th year field in its native constructor, but this app's real backend
 * (`src/agents/scheduler.py`) exclusively parses schedules through `CronTrigger.from_crontab`,
 * which is hard-coded to exactly 5 fields ("Wrong number of fields; got N, expected 5") -- a
 * Years selector here would silently do nothing real, so it's deliberately not offered.
 *
 * Day-of-week is always represented and generated as 3-letter names (mon/tue/.../sun), never
 * digits -- APScheduler's own `CronTrigger.from_crontab` documents a real, confirmed footgun:
 * "APScheduler treats 0 as Monday while the original crontab treats it as Sunday." Names
 * sidestep that ambiguity entirely, and match every existing real job's own convention already
 * (`0 2 * * sat`, `0 10 * * mon-fri`).
 *
 * Not every real cron expression is a plain comma-list per field -- steps (a "*" with a slash
 * and an interval) and numeric
 * ranges (`9-15`) are real, valid cron this multi-select model can't represent losslessly.
 * `parseCron` recognizes that honestly (`isCustom: true`, `customCron` holds the real original
 * string) rather than ever silently dropping or misreading part of an existing schedule.
 */

export const DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
export const DAY_LABELS: Record<(typeof DAY_NAMES)[number], string> = {
  mon: "Mon",
  tue: "Tue",
  wed: "Wed",
  thu: "Thu",
  fri: "Fri",
  sat: "Sat",
  sun: "Sun",
};

export const MONTH_LABELS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

export interface CronSelection {
  minutes: number[]; // 0-59, sorted ascending; [] means "*"
  hours: number[]; // 0-23
  daysOfMonth: number[]; // 1-31
  months: number[]; // 1-12
  daysOfWeek: string[]; // 3-letter lowercase names
  /** true when the real original expression uses a shape (a step, a numeric range, "L", etc.)
   * this per-field multi-select can't represent -- `customCron` is then authoritative and the
   * multi-select fields above are meaningless placeholders. */
  isCustom: boolean;
  customCron: string;
}

const DEFAULT_SELECTION: CronSelection = {
  minutes: [0],
  hours: [0],
  daysOfMonth: [],
  months: [],
  daysOfWeek: [],
  isCustom: false,
  customCron: "0 0 * * *",
};

/** A field with no selection at all defaults to "run at midnight" rather than "every minute of
 * every hour" when the user switches from Custom into the field picker -- a safe, inspectable
 * starting point rather than an accidental every-minute job. */
export function blankSelection(): CronSelection {
  return { ...DEFAULT_SELECTION };
}

function isInt(s: string): boolean {
  return /^\d+$/.test(s);
}

/** "mon-fri" -> ["mon","tue","wed","thu","fri"]; a single "sat" (no hyphen) returns null so the
 * caller treats it as a plain name instead. */
function expandDayRange(token: string): string[] | null {
  const match = /^([a-z]{3})-([a-z]{3})$/i.exec(token);
  if (!match) return null;
  const from = DAY_NAMES.indexOf(match[1].toLowerCase() as (typeof DAY_NAMES)[number]);
  const to = DAY_NAMES.indexOf(match[2].toLowerCase() as (typeof DAY_NAMES)[number]);
  if (from === -1 || to === -1) return null;
  const days: string[] = [];
  let i = from;
  for (let guard = 0; guard < 7; guard++) {
    days.push(DAY_NAMES[i]);
    if (i === to) break;
    i = (i + 1) % 7;
  }
  return days;
}

/** A plain comma-list of integers, or the bare wildcard -- anything else (a step, a range, "L")
 * returns null so the caller falls back to Custom rather than misreading it. */
function parseIntList(field: string): number[] | null {
  if (field === "*") return [];
  const values: number[] = [];
  for (const token of field.split(",")) {
    if (!isInt(token)) return null;
    values.push(Number(token));
  }
  return values;
}

function parseDayOfWeekList(field: string): string[] | null {
  if (field === "*") return [];
  const days = new Set<string>();
  for (const token of field.split(",")) {
    const trimmed = token.trim().toLowerCase();
    const range = expandDayRange(trimmed);
    if (range) {
      range.forEach((d) => days.add(d));
    } else if ((DAY_NAMES as readonly string[]).includes(trimmed)) {
      days.add(trimmed);
    } else {
      return null;
    }
  }
  return Array.from(days);
}

/** Real, best-effort parse -- an expression that isn't a plain per-field comma-list always falls
 * back to `isCustom: true` with the original string intact, never a silently-wrong guess. */
export function parseCron(cron: string): CronSelection {
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) {
    return { ...DEFAULT_SELECTION, isCustom: true, customCron: cron };
  }
  const [minStr, hourStr, domStr, monStr, dowStr] = parts;
  const minutes = parseIntList(minStr);
  const hours = parseIntList(hourStr);
  const daysOfMonth = parseIntList(domStr);
  const months = parseIntList(monStr);
  const daysOfWeek = parseDayOfWeekList(dowStr);

  if (
    minutes === null ||
    hours === null ||
    daysOfMonth === null ||
    months === null ||
    daysOfWeek === null
  ) {
    return { ...DEFAULT_SELECTION, isCustom: true, customCron: cron };
  }
  return { minutes, hours, daysOfMonth, months, daysOfWeek, isCustom: false, customCron: cron };
}

/** The inverse of `parseCron` -- when `isCustom`, returns `customCron` as-is; otherwise joins
 * each field's sorted selection into a comma-list, or "*" for an empty (every-value) field. */
export function buildCron(sel: CronSelection): string {
  if (sel.isCustom) return sel.customCron;

  const numList = (values: number[]) =>
    values.length > 0 ? [...values].sort((a, b) => a - b).join(",") : "*";

  const dayOrder: readonly string[] = DAY_NAMES;
  const dow =
    sel.daysOfWeek.length > 0
      ? [...sel.daysOfWeek].sort((a, b) => dayOrder.indexOf(a) - dayOrder.indexOf(b)).join(",")
      : "*";

  return `${numList(sel.minutes)} ${numList(sel.hours)} ${numList(sel.daysOfMonth)} ${numList(sel.months)} ${dow}`;
}
