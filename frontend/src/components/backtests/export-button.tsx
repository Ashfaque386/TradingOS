"use client";

import { useState } from "react";
import { Download } from "lucide-react";
import { api, downloadAuthenticated } from "@/lib/api";
import { Button } from "@/components/ui/button";

/** REL-043: real per-trade CSV/NDJSON export for one backtest run, mirroring the Account
 * Statement export's own authenticated-Blob-download pattern (a plain `<a href>` can't attach
 * the Bearer header this endpoint requires). */
export function ExportButton({ backtestId }: { backtestId: string }) {
  const [pending, setPending] = useState<"csv" | "ndjson" | null>(null);

  async function handleExport(format: "csv" | "ndjson") {
    setPending(format);
    try {
      await downloadAuthenticated(
        api.backtestExportPath(backtestId, format),
        `backtest-${backtestId}-trades.${format === "csv" ? "csv" : "ndjson"}`,
      );
    } finally {
      setPending(null);
    }
  }

  return (
    <div className="flex items-center gap-1.5">
      <Button
        onClick={() => handleExport("csv")}
        disabled={pending !== null}
        className="px-2.5 py-1 text-[11px]"
      >
        <Download className="h-3 w-3" />
        {pending === "csv" ? "Exporting…" : "CSV"}
      </Button>
      <Button
        onClick={() => handleExport("ndjson")}
        disabled={pending !== null}
        className="px-2.5 py-1 text-[11px]"
      >
        <Download className="h-3 w-3" />
        {pending === "ndjson" ? "Exporting…" : "NDJSON"}
      </Button>
    </div>
  );
}
