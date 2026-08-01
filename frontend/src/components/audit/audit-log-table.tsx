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
    return <p className="text-xs text-zinc-500">No audit log entries match this filter.</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-[11px]">
        <thead>
          <tr className="text-[10px] uppercase tracking-wider text-zinc-500">
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
                "cursor-pointer border-t border-white/5 transition-colors hover:bg-white/[0.03]",
                selectedId === entry.id && "bg-cyan-400/[0.06]",
              )}
            >
              <td className="py-2 pr-3 font-mono-tabular text-zinc-400">
                {new Date(entry.created_at).toLocaleString("en-IN", { hour12: false })}
              </td>
              <td className="py-2 pr-3 text-zinc-300">
                <span className="rounded-full bg-white/5 px-1.5 py-0.5 text-[9px] text-zinc-500">
                  {entry.actor_type}
                </span>{" "}
                {entry.actor_id}
              </td>
              <td className="py-2 pr-3 font-medium text-zinc-200">{entry.action}</td>
              <td className="py-2 pr-3 text-zinc-500">
                {entry.entity_type}
                {entry.entity_id && (
                  <span className="ml-1 font-mono-tabular text-zinc-600">
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
