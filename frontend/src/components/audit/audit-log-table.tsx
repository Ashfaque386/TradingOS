"use client";

import { cn } from "@/lib/utils";
import type { AuditLogEntry } from "@/lib/api";

export function AuditLogTable({
  entries,
  selectedId,
  onSelect,
}: {
  entries: AuditLogEntry[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}) {
  if (entries.length === 0) {
    return <p className="text-xs text-text-faint">No audit log entries match this filter.</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-[11px]">
        <thead>
          <tr className="text-[10px] uppercase tracking-wider text-text-faint">
            <th className="pb-2 pr-3 font-medium">Time</th>
            <th className="pb-2 pr-3 font-medium">Actor</th>
            <th className="pb-2 pr-3 font-medium">Action</th>
            <th className="pb-2 pr-3 font-medium">Entity</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <tr
              key={entry.id}
              onClick={() => onSelect(entry.id)}
              className={cn(
                "cursor-pointer border-t border-card-edge transition-colors hover:bg-bg",
                selectedId === entry.id && "bg-brand-via/[0.06]",
              )}
            >
              <td className="py-2 pr-3 font-mono-tabular text-text-dim">
                {new Date(entry.created_at).toLocaleString("en-IN", { hour12: false })}
              </td>
              <td className="py-2 pr-3 text-text-dim">
                <span className="rounded-full bg-bg px-1.5 py-0.5 text-[9px] text-text-faint">
                  {entry.actor_type}
                </span>{" "}
                {entry.actor_id}
              </td>
              <td className="py-2 pr-3 font-medium text-text">{entry.action}</td>
              <td className="py-2 pr-3 text-text-faint">
                {entry.entity_type}
                {entry.entity_id && (
                  <span className="ml-1 font-mono-tabular text-text-faint">
                    {entry.entity_id.slice(0, 8)}…
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
