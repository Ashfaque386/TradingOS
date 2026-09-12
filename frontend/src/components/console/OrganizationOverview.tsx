"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { parseBackendTimestamp } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Gated } from "@/components/ui/gated";
import { NumberTicker } from "@/components/ui/number-ticker";
import { narrationFeed } from "@/lib/ceoNarration";
import { toneClassName } from "@/lib/eventTone";
import { ApprovalQueue, AttentionQueue, DataFreshnessPanel } from "./panels";

const ACTIVE = ["planning", "running", "waiting", "stalled", "queued"];

function kpiFromSummary(rows: { total_runs: number; completed: number; failed: number; avg_duration_seconds: number | null }[]) {
  let completed = 0;
  let failed = 0;
  let durationWeightedSum = 0;
  let durationWeight = 0;
  for (const r of rows) {
    completed += r.completed;
    failed += r.failed;
    if (r.avg_duration_seconds !== null) {
      durationWeightedSum += r.avg_duration_seconds * r.total_runs;
      durationWeight += r.total_runs;
    }
  }
  const finished = completed + failed;
  return {
    successRate: finished > 0 ? completed / finished : null,
    avgDurationSeconds: durationWeight > 0 ? durationWeightedSum / durationWeight : null,
  };
}

/** spec 002 US13 (T080/T081): a short KPI tile row -- active agents, tasks completed today,
 * average task duration, success rate -- all real reads from the existing analytics/runs
 * endpoints (never a placeholder number). */
function KpiTiles() {
  const registryQuery = useQuery({ queryKey: ["agent-registry"], queryFn: api.agentRegistry });
  const summaryQuery = useQuery({
    queryKey: ["agent-analytics-summary", 30],
    queryFn: () => api.agentAnalyticsSummary(30),
  });
  const trendQuery = useQuery({
    queryKey: ["agent-analytics-trend", 1],
    queryFn: () => api.agentAnalyticsTrend(1),
  });

  const activeAgents = (registryQuery.data ?? []).filter((a) => a.live_status === "Running").length;
  const completedToday = (trendQuery.data ?? []).reduce((sum, d) => sum + d.completed, 0);
  const { successRate, avgDurationSeconds } = kpiFromSummary(summaryQuery.data ?? []);

  const tiles: { label: string; value: number | null; format: (n: number) => string }[] = [
    { label: "Active agents", value: activeAgents, format: (n) => String(Math.round(n)) },
    { label: "Completed today", value: completedToday, format: (n) => String(Math.round(n)) },
    {
      label: "Avg task duration",
      value: avgDurationSeconds,
      format: (n) => (n < 60 ? `${n.toFixed(0)}s` : `${(n / 60).toFixed(1)}m`),
    },
    {
      label: "Success rate",
      value: successRate === null ? null : successRate * 100,
      format: (n) => `${n.toFixed(0)}%`,
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {tiles.map((t) => (
        <Card key={t.label} density="dense">
          <div className="text-[10px] uppercase tracking-wide text-text-faint">{t.label}</div>
          {t.value === null ? (
            <div className="mt-1 text-lg text-text-faint">—</div>
          ) : (
            <NumberTicker
              value={t.value}
              format={t.format}
              className="mt-1 block text-lg font-semibold tabular-nums"
            />
          )}
        </Card>
      ))}
    </div>
  );
}

/** spec 002 US13: a real, present-tense feed of what the CEO is doing right now on the active
 * run -- every line traces back to a real `OrganizationalEvent` (lib/ceoNarration.ts), never
 * fabricated. Honest idle state when no run is active (AC per spec.md US13). */
function CeoNarrationFeed({ runId }: { runId: string | null }) {
  const registryQuery = useQuery({ queryKey: ["agent-registry"], queryFn: api.agentRegistry });
  const eventsQuery = useQuery({
    queryKey: ["org-events", runId],
    queryFn: () => api.orgEvents(runId as string, 0),
    enabled: runId != null,
    refetchInterval: runId != null ? 6_000 : false,
  });

  const displayNameByAgent = useMemo(
    () => Object.fromEntries((registryQuery.data ?? []).map((a) => [a.agent_name, a.display_name])),
    [registryQuery.data],
  );
  const lines = useMemo(
    () => narrationFeed(eventsQuery.data ?? [], displayNameByAgent),
    [eventsQuery.data, displayNameByAgent],
  );

  return (
    <Card eyebrow="CEO" title="What the CEO is doing now" density="dense">
      {runId == null ? (
        <p className="text-[11px] italic text-text-faint">
          No active objective — give the CEO a new one above to see live narration here.
        </p>
      ) : lines.length === 0 ? (
        <p className="text-[11px] italic text-text-faint">
          No narratable activity yet for this run.
        </p>
      ) : (
        <ul className="flex max-h-[280px] flex-col gap-1.5 overflow-y-auto">
          {lines.slice(0, 30).map((l) => (
            <li key={l.sequence} className="flex items-baseline gap-2 text-xs">
              <span
                className={`h-1.5 w-1.5 shrink-0 rounded-full ${toneClassName(l.tone)}`}
                aria-hidden
              />
              <span className="text-text-dim">{l.text}</span>
              <span className="ml-auto shrink-0 text-text-faint">
                {parseBackendTimestamp(l.occurred_at).toLocaleTimeString()}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

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
  // Runs are already ordered most-recent-first by the backend, so the first active one is the
  // CEO's current objective -- null (honest idle state) when nothing is active.
  const activeRunId = active[0]?.run_id ?? null;

  return (
    <div className="flex flex-col gap-4">
      <NewObjectivePanel />

      <KpiTiles />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <CeoNarrationFeed runId={activeRunId} />
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
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ApprovalQueue />
        <AttentionQueue />
      </div>

      <DataFreshnessPanel />

      <Card
        eyebrow="Runs"
        title="Recent runs"
        density="dense"
        action={
          <Link href="/console/runs" className="text-[11px] text-brand-via hover:underline">
            View all →
          </Link>
        }
      >
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
