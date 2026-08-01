"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { api, downloadAuthenticated } from "@/lib/api";
import { RequireAuth } from "@/lib/auth";
import { usePermission } from "@/lib/usePermission";
import { TopBar } from "@/components/layout/top-bar";
import { GlassCard } from "@/components/ui/glass-card";
import { AuditLogTable } from "@/components/audit/audit-log-table";
import { AuditEntryDetail } from "@/components/audit/audit-entry-detail";

function AuditView() {
  const [entityType, setEntityType] = useState("");
  const [actorId, setActorId] = useState("");
  const [limit, setLimit] = useState(100);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [exporting, setExporting] = useState(false);

  const logsQuery = useQuery({
    queryKey: ["audit-logs", entityType, actorId, limit],
    queryFn: () =>
      api.auditLogs({
        entity_type: entityType || undefined,
        actor_id: actorId || undefined,
        limit,
      }),
  });

  const entries = logsQuery.data ?? [];
  const selectedEntry = entries.find((e) => e.id === selectedId) ?? null;

  async function handleExport(format: "csv" | "ndjson") {
    setExporting(true);
    try {
      await downloadAuthenticated(
        api.auditExportPath({
          export_format: format,
          entity_type: entityType || undefined,
          limit,
        }),
        `audit-log.${format === "csv" ? "csv" : "ndjson"}`,
      );
    } finally {
      setExporting(false);
    }
  }

  return (
    <main className="mx-auto flex w-full max-w-[1440px] flex-1 flex-col gap-4 p-6 sm:p-8">
      <GlassCard
        eyebrow="Compliance"
        title="Audit Log"
        action={
          <div className="flex gap-2">
            <button
              onClick={() => handleExport("csv")}
              disabled={exporting}
              className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-[11px] font-medium text-zinc-300 transition hover:bg-white/10 disabled:opacity-40"
            >
              <Download className="h-3 w-3" /> CSV
            </button>
            <button
              onClick={() => handleExport("ndjson")}
              disabled={exporting}
              className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-[11px] font-medium text-zinc-300 transition hover:bg-white/10 disabled:opacity-40"
            >
              <Download className="h-3 w-3" /> NDJSON
            </button>
          </div>
        }
      >
        <div className="mb-4 flex flex-wrap gap-2 text-[11px]">
          <input
            value={entityType}
            onChange={(e) => setEntityType(e.target.value)}
            placeholder="Entity type (e.g. Order)"
            className="rounded-md border border-white/10 bg-black/30 px-2 py-1.5 text-zinc-200 placeholder:text-zinc-600"
          />
          <input
            value={actorId}
            onChange={(e) => setActorId(e.target.value)}
            placeholder="Actor ID / email"
            className="rounded-md border border-white/10 bg-black/30 px-2 py-1.5 text-zinc-200 placeholder:text-zinc-600"
          />
          <select
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            className="rounded-md border border-white/10 bg-black/30 px-2 py-1.5 text-zinc-200"
          >
            {[50, 100, 250, 500, 1000].map((n) => (
              <option key={n} value={n}>
                {n} rows
              </option>
            ))}
          </select>
        </div>

        {logsQuery.isLoading ? (
          <div className="h-40 animate-pulse rounded-xl bg-white/5" />
        ) : (
          <AuditLogTable entries={entries} selectedId={selectedId} onSelect={setSelectedId} />
        )}
      </GlassCard>

      {selectedEntry && (
        <GlassCard eyebrow="Entry Detail" title={`#${selectedEntry.id} — ${selectedEntry.action}`}>
          <AuditEntryDetail entry={selectedEntry} />
        </GlassCard>
      )}
    </main>
  );
}

export default function AuditPage() {
  const canReadAudit = usePermission("readAudit");

  return (
    <RequireAuth>
      <TopBar connected={false} subtitle="Compliance & Trade-History Audit" />
      {canReadAudit ? (
        <AuditView />
      ) : (
        <main className="mx-auto flex w-full max-w-[1440px] flex-1 items-center justify-center p-8">
          <p data-testid="audit-insufficient-role" className="text-sm text-zinc-500">
            Your role does not have access to audit logs. Requires System Administrator or
            Read-Only Auditor.
          </p>
        </main>
      )}
    </RequireAuth>
  );
}
