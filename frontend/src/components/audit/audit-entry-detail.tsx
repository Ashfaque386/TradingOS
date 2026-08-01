"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { AuditLogEntry } from "@/lib/api";

// Real entity_type values a trade/order can carry (src/core/audit.py callers, grepped across
// src/) -- only these get the "view full trade trace" link, since /trades/{id}/trace is scoped
// to that use case, not a generic entity lookup.
const TRADE_ENTITY_TYPES = new Set(["Order", "TradeSignal"]);

export function AuditEntryDetail({ entry }: { entry: AuditLogEntry }) {
  const showTrace = entry.entity_id !== null && TRADE_ENTITY_TYPES.has(entry.entity_type);
  const traceQuery = useQuery({
    queryKey: ["trade-trace", entry.entity_id],
    queryFn: () => api.tradeTrace(entry.entity_id!),
    enabled: showTrace,
  });

  return (
    <div className="rounded-xl border border-white/5 bg-black/20 p-3.5 text-[11px]">
      <div className="mb-3 grid grid-cols-2 gap-2 text-zinc-400">
        <div>
          <div className="text-[9px] uppercase tracking-wider text-zinc-600">IP Address</div>
          {entry.ip_address ?? "—"}
        </div>
        <div>
          <div className="text-[9px] uppercase tracking-wider text-zinc-600">Entity ID</div>
          <span className="font-mono-tabular">{entry.entity_id ?? "—"}</span>
        </div>
      </div>

      {/* The real tamper-evidence property this table is worth surfacing at all -- see
       * src/core/audit.py's hash-chain (SEC-038): altering any historical row invalidates every
       * subsequent entry_hash, making silent tampering detectable. */}
      <div className="mb-3 rounded-lg bg-black/30 p-2.5">
        <div className="text-[9px] uppercase tracking-wider text-zinc-600">Hash Chain</div>
        <div className="mt-1 space-y-0.5 font-mono text-[10px] text-zinc-500">
          <div>entry: {entry.entry_hash}</div>
          <div>prev: {entry.prev_entry_hash}</div>
        </div>
      </div>

      {entry.before_state && (
        <div className="mb-2">
          <div className="mb-1 text-[9px] uppercase tracking-wider text-zinc-600">
            Before State
          </div>
          <pre className="max-h-40 overflow-auto rounded-lg bg-black/40 p-2 font-mono text-[10px] text-zinc-400">
            {JSON.stringify(entry.before_state, null, 2)}
          </pre>
        </div>
      )}
      {entry.after_state && (
        <div className="mb-2">
          <div className="mb-1 text-[9px] uppercase tracking-wider text-zinc-600">
            After State
          </div>
          <pre className="max-h-40 overflow-auto rounded-lg bg-black/40 p-2 font-mono text-[10px] text-zinc-400">
            {JSON.stringify(entry.after_state, null, 2)}
          </pre>
        </div>
      )}

      {showTrace && traceQuery.data && (
        <div>
          <div className="mb-1 text-[9px] uppercase tracking-wider text-zinc-600">
            Full Trade Trace ({traceQuery.data.entries.length} entries)
          </div>
          <div className="max-h-40 space-y-1 overflow-auto">
            {traceQuery.data.entries.map((e) => (
              <div key={e.id} className="flex justify-between text-zinc-500">
                <span>{e.action}</span>
                <span className="font-mono-tabular">
                  {new Date(e.created_at).toLocaleTimeString("en-IN", { hour12: false })}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
