"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { parseBackendTimestamp } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { usePageStatus } from "@/hooks/usePageStatus";

const PAGE_SIZE = 20;
const STATUSES = [
  "queued",
  "planning",
  "running",
  "waiting",
  "paused",
  "stalled",
  "completed",
  "failed",
  "cannot_plan",
];

/** spec 002 US10: every past run is browsable, not just the most recent 20 -- server-side
 * `status`/`offset` paging (`GET /organization/runs`, already real, extended in this pass) so
 * a full history search never falls back to client-side truncation. */
export default function RunsHistoryPage() {
  usePageStatus("Run history", true);
  const [status, setStatus] = useState<string>("");
  const [page, setPage] = useState(0);

  // Fetch one extra row to know whether a next page exists, without a separate count endpoint.
  const runsQuery = useQuery({
    queryKey: ["org-runs-history", status, page],
    queryFn: () =>
      api.orgRuns(status || undefined, { limit: PAGE_SIZE + 1, offset: page * PAGE_SIZE }),
  });

  const rows = runsQuery.data ?? [];
  const hasNext = rows.length > PAGE_SIZE;
  const visible = rows.slice(0, PAGE_SIZE);

  return (
    <main className="mx-auto flex w-full max-w-[900px] flex-1 flex-col gap-4 p-6 sm:p-8">
      <Link href="/console" className="text-[11px] text-text-faint hover:underline">
        ← Command Center
      </Link>
      <div>
        <h1 className="text-lg font-semibold">Run history</h1>
        <p className="text-[11px] text-text-faint">
          Every organisation run, not just the most recent — server-side filtered and paged.
        </p>
      </div>

      <Card
        eyebrow="Runs"
        title={`Page ${page + 1}`}
        density="dense"
        action={
          <select
            className="rounded-md border border-card-edge bg-bg px-1.5 py-0.5 text-[11px]"
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setPage(0);
            }}
          >
            <option value="">All statuses</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        }
      >
        {runsQuery.isLoading ? (
          <div className="h-24 animate-pulse rounded-card bg-bg" />
        ) : visible.length === 0 ? (
          <p className="text-[11px] italic text-text-faint">
            {page === 0 ? "No runs match this filter." : "No more runs."}
          </p>
        ) : (
          <ul className="flex flex-col gap-1">
            {visible.map((r) => (
              <li key={r.run_id}>
                <Link
                  href={`/console/runs/${r.run_id}`}
                  className="flex items-baseline gap-2 rounded-md border border-card-edge px-2 py-1.5 text-xs hover:bg-bg"
                >
                  <Badge variant="outline">{r.status}</Badge>
                  <span className="truncate">{r.objective}</span>
                  <span className="ml-auto shrink-0 text-text-faint">
                    {parseBackendTimestamp(r.created_at).toLocaleString()}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}

        <div className="mt-3 flex items-center justify-between">
          <button
            className="rounded-md border border-card-edge px-2 py-1 text-[11px] disabled:opacity-40"
            disabled={page === 0}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
          >
            ← Previous
          </button>
          <button
            className="rounded-md border border-card-edge px-2 py-1 text-[11px] disabled:opacity-40"
            disabled={!hasNext}
            onClick={() => setPage((p) => p + 1)}
          >
            Next →
          </button>
        </div>
      </Card>
    </main>
  );
}
