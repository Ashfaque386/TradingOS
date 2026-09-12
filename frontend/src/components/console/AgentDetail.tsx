"use client";

import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, CircleDashed, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { parseBackendTimestamp } from "@/lib/utils";
import { agentColor, agentColorStyle } from "@/lib/agentColor";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { AgentFleet } from "./AgentFleet";
import { HandoffPanel } from "./HandoffPanel";

const NONE = "text-[11px] italic text-text-faint";
const NOT_APPLICABLE = "text-[11px] italic text-text-faint";

/** spec 002 US4: the reference-inspired two-panel "agent deep-dive + live log" workspace --
 * left = identity/current task/dependencies/waiting-reason/inputs/outputs/tools-skills/
 * provider-model/errors-retries; right = this agent's own handoffs + a real execution
 * timeline. A Fleet strip above lets the operator switch agents in place, preserving the
 * active run/task context (T074). `runId`/`taskId`, when supplied (arriving from a run's task
 * list), scope the "current task" section to that specific task via `selected_task`
 * (src/api/routers/agents.py T017) instead of only generic recent activity. */
export function AgentDetail({
  agentId,
  runId,
  taskId,
  onSwitchAgent,
}: {
  agentId: string;
  runId?: string;
  taskId?: string;
  onSwitchAgent?: (agentId: string) => void;
}) {
  const registryQuery = useQuery({ queryKey: ["agent-registry"], queryFn: api.agentRegistry });
  // The workspace links by agent *name*; a direct visit may use the AGT-xxx id. Accept either.
  const agent = registryQuery.data?.find(
    (a) => a.agent_id === agentId || a.agent_name === agentId,
  );
  const activityQuery = useQuery({
    queryKey: ["agent-activity", agent?.agent_id, runId, taskId],
    queryFn: () => api.agentActivity(agent!.agent_id, { runId, taskId }),
    enabled: !!agent,
    refetchInterval: 8_000,
  });

  const activity = activityQuery.data;
  const selectedTask = activity?.selected_task ?? null;

  if (registryQuery.isLoading) return <div className="h-40 animate-pulse rounded-card bg-bg" />;
  if (!agent)
    return (
      <Card eyebrow="Agent" title={agentId}>
        <p className={NONE}>No such agent in the registry.</p>
      </Card>
    );

  const hasCurrentTask = !!selectedTask && !["completed", "failed", "cancelled"].includes(selectedTask.status);

  return (
    <div className="flex flex-col gap-4">
      <AgentFleet
        compact
        selectedAgentId={agent.agent_name}
        onSelect={onSwitchAgent ?? (() => {})}
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Left panel: identity + current task + everything about it */}
        <div className="flex flex-col gap-4">
          <Card
            eyebrow={agent.department}
            title={agent.display_name}
            action={
              <span
                aria-hidden="true"
                className="h-3 w-3 rounded-full"
                style={{ backgroundColor: agentColor(agent.agent_name) }}
              />
            }
          >
            <div className="flex flex-wrap gap-1.5" style={agentColorStyle(agent.agent_name)}>
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
                {!agent.is_llm_backed
                  ? "no model — deterministic"
                  : activity?.resolved_model
                    ? `${activity.resolved_provider ?? "?"}/${activity.resolved_model}`
                    : "AUTO (routing.yaml) — no run yet"}
              </dd>
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

          <Card eyebrow="Current task" title={hasCurrentTask ? selectedTask!.capability : "Idle"} density="dense">
            {!hasCurrentTask ? (
              <p className={NONE}>
                {taskId ? "This task is no longer active." : "No active task — select one from a run's task list."}
              </p>
            ) : (
              <div className="flex flex-col gap-3 text-xs">
                <div>
                  <div className="text-text-muted">Objective</div>
                  <div>{selectedTask!.objective}</div>
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant="outline">{selectedTask!.status}</Badge>
                  {selectedTask!.retry_count > 0 && (
                    <span className="text-text-faint">
                      retry {selectedTask!.retry_count}/{selectedTask!.max_retries}
                    </span>
                  )}
                </div>

                <Section title="Dependencies">
                  {selectedTask!.dependencies.length === 0 ? (
                    <span className={NONE}>None — independent task.</span>
                  ) : (
                    <ul className="flex flex-col gap-1">
                      {selectedTask!.dependencies.map((d) => (
                        <li key={d.prerequisite_task_id} className="flex items-center gap-1.5">
                          <Badge variant={d.state === "satisfied" ? "secondary" : "outline"}>
                            {d.state}
                          </Badge>
                          <span>
                            {d.prerequisite_agent ?? "unknown"} · {d.required_artefact_type}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </Section>

                {selectedTask!.blocked_reason && (
                  <Section title="Waiting / blocked reason">
                    <span>{selectedTask!.blocked_reason}</span>
                  </Section>
                )}
                {selectedTask!.failure_reason && (
                  <Section title="Failure reason">
                    <span className="text-destructive">{selectedTask!.failure_reason}</span>
                  </Section>
                )}

                <Section title="Inputs">
                  {selectedTask!.required_inputs.length === 0 ? (
                    <span className={NONE}>No declared inputs.</span>
                  ) : (
                    <div className="flex flex-wrap gap-1">
                      {selectedTask!.required_inputs.map((t) => {
                        const received = selectedTask!.received_inputs.some((r) => r.type === t);
                        return (
                          <Badge key={t} variant={received ? "secondary" : "outline"}>
                            {t}
                          </Badge>
                        );
                      })}
                    </div>
                  )}
                </Section>

                <Section title="Downstream consumers">
                  {selectedTask!.downstream_consumers.length === 0 ? (
                    <span className={NONE}>Nothing consumes this task&apos;s output yet.</span>
                  ) : (
                    <ul className="flex flex-col gap-1">
                      {selectedTask!.downstream_consumers.map((c) => (
                        <li key={c.task_id}>
                          {c.agent ?? "unknown"} · {c.required_artefact_type} ({c.state})
                        </li>
                      ))}
                    </ul>
                  )}
                </Section>

                <Section title="Tools / skills">
                  {selectedTask!.granted_skills.length === 0 ? (
                    <span className={NONE}>No skills granted to this agent.</span>
                  ) : (
                    <div className="flex flex-wrap gap-1">
                      {selectedTask!.granted_skills.map((s) => (
                        <Badge key={s} variant="outline">
                          {s}
                        </Badge>
                      ))}
                    </div>
                  )}
                </Section>

                <Section title="Audit">
                  {selectedTask!.audit_reference != null ? (
                    <span>audit_log #{selectedTask!.audit_reference}</span>
                  ) : (
                    <span className={NOT_APPLICABLE}>not yet linked</span>
                  )}
                </Section>
              </div>
            )}
          </Card>
        </div>

        {/* Right panel: this agent's own activity -- handoffs + a real execution timeline */}
        <div className="flex flex-col gap-4">
          {runId ? (
            <HandoffPanel runId={runId} agentName={agent.agent_name} />
          ) : (
            <Card eyebrow="Handoffs" title="Handoffs" density="dense">
              <p className={NONE}>Open this agent from a specific run to see its handoffs.</p>
            </Card>
          )}

          <Card eyebrow="History" title="Execution timeline" density="dense">
            {!activity || activity.recent_runs.length === 0 ? (
              <p className={NONE}>No runs recorded yet.</p>
            ) : (
              <ol className="flex flex-col gap-2 text-xs">
                {activity.recent_runs.map((r) => (
                  <li key={r.run_id} className="flex items-start gap-2">
                    <TimelineIcon status={r.status} />
                    <div>
                      <div className="flex items-center gap-1.5">
                        <Badge variant={r.status === "Failed" ? "destructive" : "outline"}>
                          {r.status}
                        </Badge>
                        <span className="text-text-faint">
                          {r.started_at ? parseBackendTimestamp(r.started_at).toLocaleString() : "—"}
                        </span>
                      </div>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </Card>

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
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1 text-[10px] font-medium uppercase tracking-[0.14em] text-text-faint">
        {title}
      </div>
      {children}
    </div>
  );
}

function TimelineIcon({ status }: { status: string }) {
  if (status === "Completed") return <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-up" />;
  if (status === "Running") return <Loader2 className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin text-text-muted" />;
  return <CircleDashed className="mt-0.5 h-3.5 w-3.5 shrink-0 text-text-faint" />;
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
  if (t.status === "escalated") return "Escalated to the CEO for review.";
  return "";
}
