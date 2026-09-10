"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type OrgEvent } from "@/lib/api";
import { Card } from "@/components/ui/card";

/** FR-087: reconstruct a finished run from its ordered event log -- plan created, tasks
 * started/completed, dependencies satisfied, hand-offs, retries, decisions, approval, outcome.
 * A scrubber steps through `sequence`; the summary reflects only events up to that point. */
export function RunReplay({ runId }: { runId: string }) {
  const { data: events, isLoading } = useQuery({
    queryKey: ["org-events", runId, "replay"],
    queryFn: () => api.orgEvents(runId, 0),
  });
  const [cursor, setCursor] = useState<number>(0);

  const ordered = useMemo(
    () => (events ?? []).slice().sort((a, b) => a.sequence - b.sequence),
    [events],
  );
  const max = ordered.length;
  const upto = ordered.slice(0, cursor || max);

  const rollup = useMemo(() => rollupOf(upto), [upto]);

  if (isLoading) return <Card eyebrow="Replay" title="Run replay"><div className="h-10 animate-pulse rounded bg-bg" /></Card>;
  if (max === 0)
    return (
      <Card eyebrow="Replay" title="Run replay">
        <p className="text-[11px] italic text-text-faint">No events recorded for this run.</p>
      </Card>
    );

  return (
    <Card eyebrow="Replay" title="Run replay">
      <input
        type="range"
        min={1}
        max={max}
        value={cursor || max}
        onChange={(e) => setCursor(Number(e.target.value))}
        className="w-full"
        aria-label="Replay position"
      />
      <div className="mt-1 text-[11px] text-text-faint">
        event {cursor || max} / {max} · {upto.at(-1)?.event_type}
      </div>
      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        {Object.entries(rollup).map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-text-muted">{k}</dt>
            <dd className="text-right font-medium">{v}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

function rollupOf(events: OrgEvent[]): Record<string, string | number> {
  const count = (prefix: string) => events.filter((e) => e.event_type.startsWith(prefix)).length;
  const has = (type: string) => (events.some((e) => e.event_type === type) ? "yes" : "—");
  return {
    "plan created": has("organization.plan.created"),
    "tasks started": count("task.started"),
    "tasks completed": count("task.completed"),
    "tasks retrying": count("task.retrying"),
    "tasks blocked": count("task.blocked"),
    "dependencies satisfied": count("dependency.satisfied"),
    "conflicts": count("ceo.conflict_detected"),
    "decisions": count("ceo.decision.created"),
    "approval requested": has("approval.requested"),
    "approval approved": has("approval.approved"),
    "approval rejected": has("approval.rejected"),
    "outcome": events.some((e) => e.event_type === "organization.run.completed")
      ? "completed"
      : events.some((e) => e.event_type === "organization.run.failed")
        ? "failed"
        : "in progress",
  };
}
