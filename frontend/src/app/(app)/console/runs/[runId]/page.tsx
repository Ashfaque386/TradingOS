"use client";

import { use } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { usePageStatus } from "@/hooks/usePageStatus";
import { useOrganizationStream } from "@/hooks/useOrganizationStream";
import {
  ActivityStream,
  ArtefactList,
  DecisionHistory,
  DependencyPanel,
  DepartmentView,
  OrgTaskGraph,
  RunReplay,
  taskStateExplainer,
} from "@/components/console";

export default function RunWorkspace({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = use(params);
  const { connected, events: live } = useOrganizationStream([runId]);
  usePageStatus("Run workspace", connected);

  const runQuery = useQuery({ queryKey: ["org-run", runId], queryFn: () => api.orgRun(runId) });
  const tasksQuery = useQuery({ queryKey: ["org-tasks", runId], queryFn: () => api.orgTasks(runId) });
  const depsQuery = useQuery({
    queryKey: ["org-dependencies", runId],
    queryFn: () => api.orgDependencies(runId),
  });
  const decisionsQuery = useQuery({
    queryKey: ["org-decisions", runId],
    queryFn: () => api.orgDecisions(runId),
  });
  const artefactsQuery = useQuery({
    queryKey: ["org-artefacts", runId],
    queryFn: () => api.orgArtefacts(runId),
  });
  const eventsQuery = useQuery({
    queryKey: ["org-events", runId],
    queryFn: () => api.orgEvents(runId, 0),
  });

  const run = runQuery.data;
  const tasks = tasksQuery.data ?? [];
  const deps = depsQuery.data ?? [];
  const mergedEvents = mergeEvents(eventsQuery.data ?? [], live);
  const terminal = run && ["completed", "failed", "cannot_plan", "cancelled"].includes(run.status);

  return (
    <main className="mx-auto flex w-full max-w-[1440px] flex-1 flex-col gap-4 p-6 sm:p-8">
      <div className="flex items-center gap-3">
        <Link href="/console" className="text-[11px] text-text-faint hover:underline">
          ← Command Center
        </Link>
        <Badge variant={connected ? "secondary" : "destructive"}>
          {connected ? "live" : "reconnecting"}
        </Badge>
      </div>

      <Card eyebrow="Run" title={run?.objective ?? runId}>
        {run ? (
          <div className="flex flex-wrap gap-1.5">
            <Badge variant="outline">{run.status}</Badge>
            <Badge variant="outline">source: {run.source}</Badge>
            <Badge variant="outline">approvals pending: {run.pending_approvals}</Badge>
            {Object.entries(run.task_counts).map(([s, n]) => (
              <Badge key={s} variant="outline">
                {s}: {n}
              </Badge>
            ))}
            {Object.entries(run.dataset_freshness).map(([d, s]) => (
              <Badge key={d} variant={s === "fresh" ? "secondary" : "destructive"}>
                {d}: {s}
              </Badge>
            ))}
          </div>
        ) : (
          <div className="h-8 animate-pulse rounded bg-bg" />
        )}
      </Card>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="xl:col-span-2">
          <OrgTaskGraph tasks={tasks} dependencies={deps} />
        </div>
        <ActivityStream events={mergedEvents} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <DependencyPanel tasks={tasks} dependencies={deps} />
        <DecisionHistory decisions={decisionsQuery.data ?? []} />
        <DepartmentView tasks={tasks} />
      </div>

      <Card eyebrow="Tasks" title="Task detail" density="dense">
        {tasks.length === 0 ? (
          <p className="text-[11px] italic text-text-faint">No tasks yet.</p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {tasks.map((t) => {
              const note = taskStateExplainer(t);
              return (
                <li key={t.task_id} className="rounded-lg border border-card-edge p-2 text-xs">
                  <div className="flex items-center gap-2">
                    <Badge variant="outline">{t.status}</Badge>
                    <Link
                      href={`/console/agents/${t.assigned_agent}`}
                      className="font-medium hover:underline"
                    >
                      {t.assigned_agent}
                    </Link>
                    <span className="text-text-muted">· {t.capability}</span>
                    {t.ran_concurrently && <span className="text-text-faint">· ran ∥</span>}
                    {t.dependency_wait_seconds > 0 && (
                      <span className="text-text-faint">
                        · waited {t.dependency_wait_seconds}s
                      </span>
                    )}
                  </div>
                  {note && <div className="mt-0.5 text-text-muted">{note}</div>}
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ArtefactList artefacts={artefactsQuery.data ?? []} />
        {terminal && <RunReplay runId={runId} />}
      </div>
    </main>
  );
}

function mergeEvents<T extends { sequence: number }>(a: T[], b: T[]): T[] {
  const seen = new Set<number>();
  const out: T[] = [];
  for (const e of [...a, ...b]) {
    if (seen.has(e.sequence)) continue;
    seen.add(e.sequence);
    out.push(e);
  }
  return out;
}
