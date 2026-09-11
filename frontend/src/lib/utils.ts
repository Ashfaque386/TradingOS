import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Every backend timestamp is a naive-UTC value (this project's own established storage
 * convention) serialized with no trailing "Z"/offset -- confirmed live:
 * `GET /agents/runs` returns `"started_at": "2026-09-11T16:25:52.289022"`. Per the ECMAScript
 * spec, `new Date()` on a date-time string with no timezone designator is parsed as *local*
 * time, not UTC -- in an IST browser this silently shifted every "started_at"/"ended_at" 5.5
 * hours into the future, making "just now" read as "~6h ago" (found investigating exactly that
 * report against a run that had just failed). Appending "Z" only when one isn't already present
 * keeps this safe to call on a value that's already correctly tagged (an ISO string from
 * `Date.prototype.toISOString()`, for instance). Use this instead of a bare `new Date(iso)`
 * anywhere a backend timestamp feeds real time math (a "time ago" label, a duration, a
 * scheduling comparison) -- plain display formatting that already round-trips through this first
 * is equally correct either way. */
export function parseBackendTimestamp(iso: string): Date {
  return new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
}

export function formatINR(value: number, opts?: { showSign?: boolean }): string {
  const sign = opts?.showSign && value > 0 ? "+" : "";
  return (
    sign +
    new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: "INR",
      maximumFractionDigits: 0,
    }).format(value)
  );
}

export function formatCompactINR(value: number): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  if (abs >= 1e7) return `${sign}₹${(abs / 1e7).toFixed(2)}Cr`;
  if (abs >= 1e5) return `${sign}₹${(abs / 1e5).toFixed(2)}L`;
  if (abs >= 1e3) return `${sign}₹${(abs / 1e3).toFixed(1)}K`;
  return `${sign}₹${abs.toFixed(0)}`;
}
