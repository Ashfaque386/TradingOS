"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { parseBackendTimestamp } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const NONE = "text-[11px] italic text-text-faint";

/** FR-082: the uniform agent detail view -- identical sections for a graph node and a scheduled
 * agent alike. FR-083/084: a waiting task states what it waits for; a failed task states the
 * reason, not just "Failed". Every section renders real data or an explicit "no data yet". */
export function AgentDetail({ agentId }: { agentId: string }) {
  const registryQuery = useQuery({ queryKey: ["agent-registry"], queryFn: api.agentRegistry });
  // The workspace links by agent *name*; a direct visit may use the AGT-xxx id. Accept either.
  const agent = registryQuery.data?.find(
    (a) => a.agent_id === agentId || a.agent_name === agentId,
  );
  const activityQuery = useQuery({
    queryKey: ["agent-activity", agent?.agent_id],
    queryFn: () => api.agentActivity(agent!.agent_id),
    enabled: !!agent,
    refetchInterval: 10_000,
  });

  const activity = activityQuery.data;

  if (registryQuery.isLoading) return <div className="h-40 animate-pulse rounded-card bg-bg" />;
  if (!agent)
    return (
      <Card eyebrow="Agent" title={agentId}>
        <p className={NONE}>No such agent in the registry.</p>
      </Card>
    );

  return (
    <div className="flex flex-col gap-4">
      <Card eyebrow={agent.department} title={agent.display_name}>
        <div className="flex flex-wrap gap-1.5">
          <Badge variant="outline">{agent.kind}</Badge>
          <Badge variant={agent.health === "degraded" ? "destructive" : "secondary"}>
            {agent.health}
          </Badge>
          <Badge variant={agent.enabled ? "secondary" : "destructive"}>
            {agent.enabled ? "enabled" : "disabled"}
          </Badge>
        </div>
        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
          <dt className="text-text-muted">Model / provider</dt>
          <dd className="text-right font-medium">
            {agent.is_llm_backed ? "AUTO (routing.yaml)" : "no model — deterministic"}
          </dd>
          <dt className="text-text-muted">Capabilities</dt>
          <dd className="text-right">{agent.capabilities.join(", ") || "—"}</dd>
          <dt className="text-text-muted">Last execution</dt>
          <dd className="text-right">
            {agent.last_execution
              ? parseBackendTimestamp(agent.last_execution).toLocaleString()
              : "never"}
          </dd>
          <dt className="text-text-muted">Next scheduled</dt>
          <dd className="text-right">
            {agent.next_scheduled_execution
              ? parseBackendTimestamp(agent.next_scheduled_execution).toLocaleString()
              : "event-driven"}
          </dd>
        </dl>
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card eyebrow="History" title="Recent runs" density="dense">
          {!activity || activity.recent_runs.length === 0 ? (
            <p className={NONE}>No runs recorded yet.</p>
          ) : (
            <ul className="flex flex-col gap-1 text-xs">
              {activity.recent_runs.map((r) => (
                <li key={r.run_id} className="flex items-baseline gap-2">
                  <Badge variant={r.status === "Failed" ? "destructive" : "outline"}>
                    {r.status}
                  </Badge>
                  <span className="text-text-faint">
                    {r.started_at ? parseBackendTimestamp(r.started_at).toLocaleString() : "—"}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card eyebrow="Delegated work" title="Recent tasks" density="dense">
          {!activity || activity.recent_tasks.length === 0 ? (
            <p className={NONE}>No organisation tasks assigned yet.</p>
          ) : (
            <ul className="flex flex-col gap-1.5 text-xs">
              {activity.recent_tasks.map((t) => (
                <li key={t.task_id} className="rounded-lg border border-card-edge p-2">
                  <div className="flex items-center gap-2">
                    <Badge variant="outline">{t.status}</Badge>
                    <span className="font-medium">{t.capability}</span>
                  </div>
                  <div className="text-text-muted">{t.objective}</div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card eyebrow="Outputs" title="Recent result artefacts" density="dense">
        {!activity || activity.recent_outputs.length === 0 ? (
          <p className={NONE}>No result artefacts yet.</p>
        ) : (
          <ul className="flex flex-col gap-1 text-xs">
            {activity.recent_outputs.map((a) => (
              <li key={a.artefact_id} className="flex items-baseline gap-2">
                <Badge variant="outline">{a.artefact_type}</Badge>
                {a.disposition && <span className="text-text-faint">{a.disposition}</span>}
                <span className="ml-auto text-text-faint">
                  {a.created_at ? parseBackendTimestamp(a.created_at).toLocaleString() : "—"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

/** FR-083/084 helper: a plain-language explanation of a task's non-terminal / failed state, for
 * the run workspace's task rows. */
export function taskStateExplainer(t: {
  status: string;
  blocked_reason: string | null;
  failure_reason: string | null;
  retry_count: number;
  depends_on: string[];
}): string {
  if (t.status.startsWith("waiting"))
    return `Waiting on ${t.depends_on.length} upstream task(s); next: a dependency.satisfied event.`;
  if (t.status === "blocked")
    return `Blocked: ${t.blocked_reason ?? "an upstream prerequisite failed"}. The CEO will re-plan or escalate.`;
  if (t.status === "failed")
    return `Failed after ${t.retry_count} retr${t.retry_count === 1 ? "y" : "ies"}: ${
      t.failure_reason ?? "no reason recorded"
    }.`;
  if (t.status === "retrying") return `Retrying (attempt ${t.retry_count}).`;
  return "";
}
