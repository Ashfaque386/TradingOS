"use client";

import { useMemo, useState } from "react";
import type { OrgEvent } from "@/lib/api";
import { parseBackendTimestamp } from "@/lib/utils";
import { Card } from "@/components/ui/card";

/** FR-088/172: the ordered `OrganizationalEvent` feed for the selected run, filterable by
 * event-type family. Rendered from the live stream buffer merged with the initial fetch. */
export function ActivityStream({ events }: { events: OrgEvent[] }) {
  const [filter, setFilter] = useState<string>("all");

  const families = useMemo(() => {
    const set = new Set<string>(["all"]);
    for (const e of events) set.add(e.event_type.split(".")[0]);
    return [...set];
  }, [events]);

  const shown = useMemo(() => {
    const ordered = [...events].sort((a, b) => b.sequence - a.sequence);
    return filter === "all"
      ? ordered
      : ordered.filter((e) => e.event_type.startsWith(filter));
  }, [events, filter]);

  return (
    <Card
      eyebrow="Live"
      title="Activity stream"
      density="dense"
      action={
        <select
          className="rounded-md border border-card-edge bg-bg px-1.5 py-0.5 text-[11px]"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        >
          {families.map((f) => (
            <option key={f} value={f}>
              {f}
            </option>
          ))}
        </select>
      }
    >
      {shown.length === 0 ? (
        <p className="text-[11px] italic text-text-faint">No events yet.</p>
      ) : (
        <ul className="flex max-h-[520px] flex-col gap-1 overflow-y-auto">
          {shown.slice(0, 250).map((e) => (
            <li
              key={`${e.sequence}-${e.event_type}`}
              className="flex items-baseline gap-2 border-b border-card-edge/50 py-1 text-[11px] last:border-0"
            >
              <span className="w-8 shrink-0 text-right text-text-faint">#{e.sequence}</span>
              <span className="font-medium text-text">{e.event_type}</span>
              <span className="truncate text-text-muted">
                {e.subject_type}
                {e.subject_id ? ` ${String(e.subject_id).slice(0, 8)}` : ""}
              </span>
              <span className="ml-auto shrink-0 text-text-faint">
                {parseBackendTimestamp(e.occurred_at).toLocaleTimeString()}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
