"use client";

// Phase 2E: no dedicated alerts-feed endpoint exists on the backend -- only audit-log data (real
// trades, risk events, kill-switch actions, etc.) and static notification-channel *configuration*
// (Telegram/Slack routing, not a feed itself). Built as a real "Recent Activity" feed off the
// same api.auditLogs() endpoint the Audit page already uses, rather than inventing fake data or a
// new backend. Gated by the same `readAudit` permission the Audit page itself requires -- the
// underlying data is audit-log data regardless of which UI surface renders it.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import { api } from "@/lib/api";
import { usePermission } from "@/lib/usePermission";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import type { AuditLogEntry } from "@/lib/api";

const LAST_SEEN_KEY = "tradingos_notifications_last_seen";

function relativeTime(iso: string): string {
  const deltaMs = Date.now() - new Date(iso).getTime();
  const minutes = Math.round(deltaMs / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function describeEntry(entry: AuditLogEntry): string {
  const entity = entry.entity_id ? `${entry.entity_type} ${entry.entity_id.slice(0, 8)}` : entry.entity_type;
  return `${entry.action} · ${entity}`;
}

export function NotificationCenter() {
  const canRead = usePermission("readAudit");
  const [open, setOpen] = useState(false);
  // Lazy initializer, not an effect -- safe because `entries` is always [] on first paint
  // regardless (the query hasn't resolved yet), so `unseenCount` can't diverge between the SSR
  // pass and the client's hydration render no matter what this reads.
  const [lastSeen, setLastSeen] = useState<string | null>(() =>
    typeof window !== "undefined" ? window.localStorage.getItem(LAST_SEEN_KEY) : null,
  );

  const feedQuery = useQuery({
    queryKey: ["notification-feed"],
    queryFn: () => api.auditLogs({ limit: 20 }),
    enabled: canRead,
    refetchInterval: 20_000,
  });

  const entries = feedQuery.data ?? [];
  const unseenCount =
    lastSeen === null ? entries.length : entries.filter((e) => e.created_at > lastSeen).length;

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (next && entries.length > 0) {
      const newest = entries[0].created_at;
      window.localStorage.setItem(LAST_SEEN_KEY, newest);
      setLastSeen(newest);
    }
  }

  if (!canRead) return null;

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger
        className="relative rounded-md p-1.5 text-text-faint outline-none transition hover:bg-bg hover:text-text-dim focus-visible:ring-2 focus-visible:ring-ring"
        aria-label="Recent activity"
      >
        <Bell className="h-4 w-4" />
        {unseenCount > 0 && (
          <span className="absolute -top-0.5 -right-0.5 flex h-3.5 min-w-[14px] items-center justify-center rounded-full bg-brand-via px-1 text-[8px] font-semibold text-white">
            {unseenCount > 9 ? "9+" : unseenCount}
          </span>
        )}
      </PopoverTrigger>
      <PopoverContent align="end" sideOffset={10} className="w-80 gap-0 p-0">
        <div className="flex items-center justify-between border-b border-card-edge px-3 py-2">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-text-faint">
            Recent Activity
          </span>
          <span className="text-[10px] text-text-faint">from the audit log</span>
        </div>
        <div className="max-h-80 overflow-y-auto p-1.5">
          {feedQuery.isLoading ? (
            <div className="m-1.5 h-24 animate-pulse rounded-lg bg-bg" />
          ) : entries.length === 0 ? (
            <p className="px-2 py-4 text-center text-xs text-text-faint">No recent activity.</p>
          ) : (
            entries.map((entry) => (
              <div key={entry.id} className="flex flex-col gap-0.5 rounded-lg px-2 py-1.5 hover:bg-bg">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[11px] font-medium text-text">{describeEntry(entry)}</span>
                  <span className="shrink-0 font-mono-tabular text-[9px] text-text-faint">
                    {relativeTime(entry.created_at)}
                  </span>
                </div>
                <span className="text-[10px] text-text-faint">
                  {entry.actor_type} · {entry.actor_id}
                </span>
              </div>
            ))
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
