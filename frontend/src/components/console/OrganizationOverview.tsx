"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { parseBackendTimestamp } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Gated } from "@/components/ui/gated";
import { ApprovalQueue, AttentionQueue, DataFreshnessPanel } from "./panels";

const ACTIVE = ["planning", "running", "waiting", "stalled", "queued"];

/** The one place to start real work now that /agents (the old single-thread trigger page) is
 * retired -- POST /organization/runs, the CEO-led path every quickstart scenario assumes.
 * Fully hidden (not shown-then-403) for a role that can't create a run, matching this console's
 * own established Gated convention (ApprovalQueue's approve/reject controls). */
function NewObjectivePanel() {
  const queryClient = useQueryClient();
  const [objective, setObjective] = useState("");
  const [error, setError] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: (value: string) => api.orgCreateRun(value),
    onSuccess: () => {
      setObjective("");
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["org-runs"] });
    },
    onError: (e: unknown) => setError(e instanceof Error ? e.message : "failed to create run"),
  });

  return (
    <Gated permission="createOrgRun">
      <Card eyebrow="CEO" title="New objective" density="dense">
        <form
          className="flex flex-col gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            const value = objective.trim();
            if (value.length >= 3) create.mutate(value);
          }}
        >
          <textarea
            className="w-full rounded-md border border-card-edge bg-bg p-2 text-xs"
            placeholder="e.g. Find low-risk swing opportunities for tomorrow"
            value={objective}
            onChange={(e) => setObjective(e.target.value)}
            rows={2}
          />
          <button
            type="submit"
            disabled={objective.trim().length < 3 || create.isPending}
            className="self-start rounded-md bg-primary px-3 py-1.5 text-[11px] font-medium text-primary-foreground disabled:opacity-50"
          >
            {create.isPending ? "Submitting…" : "Give the CEO an objective"}
          </button>
          {error && <p className="text-[11px] text-destructive">{error}</p>}
        </form>
      </Card>
    </Gated>
  );
}

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
      <NewObjectivePanel />

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

      <DataFreshnessPanel />

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
                    {parseBackendTimestamp(r.created_at).toLocaleString()}
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
