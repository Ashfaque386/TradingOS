"use client";

import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, AlertTriangle } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/card";

/** REL-067: real per-symbol ingestion freshness, via GET /market/datalake/status -- the exact
 * same check (src/data/datalake/freshness.py) the Scheduler's own pre-research-cycle gate
 * already enforces before a research cycle can run. This endpoint has existed since REL-010; this
 * is its first frontend consumer. */
export function DataFreshnessStrip() {
  const statusQuery = useQuery({
    queryKey: ["datalake-status"],
    queryFn: api.datalakeStatus,
    refetchInterval: 5 * 60_000,
  });

  const status = statusQuery.data;

  return (
    <Card eyebrow="Daily EOD Data Lake" title="Data Freshness" density="dense">
      {statusQuery.isLoading ? (
        <div className="h-10 animate-pulse rounded-xl bg-bg" />
      ) : !status ? (
        <p className="text-xs text-text-faint">Could not reach the freshness check.</p>
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            {status.status === "Fresh" ? (
              <CheckCircle2 className="h-4 w-4 text-up" />
            ) : (
              <AlertTriangle className="h-4 w-4 text-warn" />
            )}
            <span
              className={cn(
                "text-sm font-semibold",
                status.status === "Fresh" ? "text-up" : "text-warn",
              )}
            >
              {status.status}
            </span>
            <span className="text-xs text-text-faint">as of {status.as_of}</span>
          </div>
          <span className="text-[11px] text-text-faint">
            {status.total_symbols} symbols tracked
            {status.stale_symbols.length > 0 && (
              <> · {status.stale_symbols.length} stale</>
            )}
          </span>
        </div>
      )}
      {status && status.stale_symbols.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5 border-t border-card-edge pt-3">
          {status.stale_symbols.slice(0, 12).map((s) => (
            <span
              key={s.symbol}
              className="rounded-md bg-warn/10 px-2 py-1 text-[11px] font-medium text-warn"
            >
              {s.symbol}
            </span>
          ))}
          {status.stale_symbols.length > 12 && (
            <span className="px-2 py-1 text-[11px] text-text-faint">
              +{status.stale_symbols.length - 12} more
            </span>
          )}
        </div>
      )}
    </Card>
  );
}
