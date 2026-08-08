"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { api, downloadAuthenticated } from "@/lib/api";
import { usePermission } from "@/lib/usePermission";
import { usePageStatus } from "@/hooks/usePageStatus";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
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
      <Card
        eyebrow="Compliance"
        title="Audit Log"
        action={
          <div className="flex gap-2">
            <Button onClick={() => handleExport("csv")} disabled={exporting} variant="secondary" className="px-3 py-1.5 text-[11px]">
              <Download className="h-3 w-3" /> CSV
            </Button>
            <Button onClick={() => handleExport("ndjson")} disabled={exporting} variant="secondary" className="px-3 py-1.5 text-[11px]">
              <Download className="h-3 w-3" /> NDJSON
            </Button>
          </div>
        }
      >
        <div className="mb-4 flex flex-wrap gap-2 text-[11px]">
          <input
            value={entityType}
            onChange={(e) => setEntityType(e.target.value)}
            placeholder="Entity type (e.g. Order)"
            className="rounded-md border border-card-edge bg-bg px-2 py-1.5 text-text placeholder:text-text-faint"
          />
          <input
            value={actorId}
            onChange={(e) => setActorId(e.target.value)}
            placeholder="Actor ID / email"
            className="rounded-md border border-card-edge bg-bg px-2 py-1.5 text-text placeholder:text-text-faint"
          />
          <select
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            className="rounded-md border border-card-edge bg-bg px-2 py-1.5 text-text"
          >
            {[50, 100, 250, 500, 1000].map((n) => (
              <option key={n} value={n}>
                {n} rows
              </option>
            ))}
          </select>
        </div>

        {logsQuery.isLoading ? (
          <div className="h-40 animate-pulse rounded-xl bg-bg" />
        ) : (
          <AuditLogTable entries={entries} selectedId={selectedId} onSelect={setSelectedId} />
        )}
      </Card>

      {selectedEntry && (
        <Card eyebrow="Entry Detail" title={`#${selectedEntry.id} — ${selectedEntry.action}`}>
          <AuditEntryDetail entry={selectedEntry} />
        </Card>
      )}
    </main>
  );
}

export default function AuditPage() {
  const canReadAudit = usePermission("readAudit");

  usePageStatus("Compliance & Trade-History Audit", false);

  return canReadAudit ? (
    <AuditView />
  ) : (
    <main className="mx-auto flex w-full max-w-[1440px] flex-1 items-center justify-center p-8">
      <p data-testid="audit-insufficient-role" className="text-sm text-text-faint">
        Your role does not have access to audit logs. Requires System Administrator or
        Read-Only Auditor.
      </p>
    </main>
  );
}
