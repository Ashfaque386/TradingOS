"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ApprovalQueue, AttentionQueue } from "./panels";

const ACTIVE = ["planning", "running", "waiting", "stalled", "queued"];

/** FR-080: console home -- CEO status (are runs planning/running), org health counts, pending
 * approvals, recent decisions & failures, all from real backend reads. No hard-coded status. */
export function OrganizationOverview() {
  const runsQuery = useQuery({
    queryKey: ["org-runs"],
    queryFn: () => api.orgRuns(),
    refetchInterval: 6_000,
  });
  const runs = runsQuery.data ?? [];
  const byStatus = runs.reduce<Record<string, number>>((acc, r) => {
    acc[r.status] = (acc[r.status] ?? 0) + 1;
    return acc;
  }, {});
  const active = runs.filter((r) => ACTIVE.includes(r.status));

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card eyebrow="CEO" title="Organisation status" density="dense">
          {runsQuery.isLoading ? (
            <div className="h-10 animate-pulse rounded bg-bg" />
          ) : (
            <>
              <div className="text-2xl font-semibold">
                {active.length} active {active.length === 1 ? "run" : "runs"}
              </div>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {Object.entries(byStatus).map(([s, n]) => (
                  <Badge key={s} variant="outline">
                    {s}: {n}
                  </Badge>
                ))}
                {runs.length === 0 && (
                  <span className="text-[11px] italic text-text-faint">
                    No organisation runs yet.
                  </span>
                )}
              </div>
            </>
          )}
        </Card>
        <ApprovalQueue />
        <AttentionQueue />
      </div>

      <Card eyebrow="Runs" title="Recent runs" density="dense">
        {runs.length === 0 ? (
          <p className="text-[11px] italic text-text-faint">Nothing to show.</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {runs.slice(0, 20).map((r) => (
              <li key={r.run_id}>
                <Link
                  href={`/console/runs/${r.run_id}`}
                  className="flex items-baseline gap-2 rounded-md border border-card-edge px-2 py-1.5 text-xs hover:bg-bg"
                >
                  <Badge variant="outline">{r.status}</Badge>
                  <span className="truncate">{r.objective}</span>
                  <span className="ml-auto shrink-0 text-text-faint">
                    {new Date(r.created_at).toLocaleString()}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
