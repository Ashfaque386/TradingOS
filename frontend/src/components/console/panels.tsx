"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  type OrgArtefact,
  type OrgDecision,
  type OrgDependency,
  type OrgPlannedTask,
  type OrgTask,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const NONE = "text-[11px] text-text-faint italic";

/** FR-041: "ready when ✓ / ⏳ …" -- each hard dependency of each not-yet-complete task, with a
 * real satisfied / waiting marker derived from the dependency's own `state`. */
export function DependencyPanel({
  tasks,
  dependencies,
}: {
  tasks: OrgTask[];
  dependencies: OrgDependency[];
}) {
  const label = new Map(tasks.map((t) => [t.task_id, `${t.capability} (${t.assigned_agent})`]));
  const pending = tasks.filter(
    (t) => !["completed", "cancelled", "superseded"].includes(t.status),
  );
  return (
    <Card eyebrow="Dependencies" title="Ready when…" density="dense">
      {pending.length === 0 ? (
        <p className={NONE}>No tasks are waiting on a dependency.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {pending.map((t) => {
            const deps = dependencies.filter((d) => d.dependent_task_id === t.task_id);
            return (
              <li key={t.task_id} className="rounded-lg border border-card-edge p-2">
                <div className="text-xs font-medium">{label.get(t.task_id) ?? t.capability}</div>
                {deps.length === 0 ? (
                  <div className={NONE}>no upstream dependencies</div>
                ) : (
                  <ul className="mt-1 flex flex-col gap-0.5">
                    {deps.map((d) => (
                      <li key={d.prerequisite_task_id} className="text-[11px] text-text-muted">
                        {d.state === "satisfied" ? "✓" : "⏳"}{" "}
                        {label.get(d.prerequisite_task_id) ?? d.required_artefact_type}
                        {d.policy === "soft" && " (soft)"}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

/** FR-023: operational summaries only -- `summary`, `reason`, `next_step`. Never private
 * chain-of-thought (the API never sends it). */
export function DecisionHistory({ decisions }: { decisions: OrgDecision[] }) {
  return (
    <Card eyebrow="CEO" title="Decisions" density="dense">
      {decisions.length === 0 ? (
        <p className={NONE}>No decisions recorded for this run yet.</p>
      ) : (
        <ol className="flex flex-col gap-2">
          {decisions.map((d) => (
            <li key={d.decision_id} className="rounded-lg border border-card-edge p-2">
              <div className="flex items-center gap-2">
                <Badge variant="outline">{d.decision_type}</Badge>
                {d.escalated_to_role && (
                  <Badge variant="destructive">→ {d.escalated_to_role}</Badge>
                )}
                {d.resolved_by && <Badge variant="secondary">resolved</Badge>}
              </div>
              <div className="mt-1 text-xs font-medium">{d.summary}</div>
              <div className="text-[11px] text-text-muted">{d.reason}</div>
              {d.next_step && (
                <div className="mt-0.5 text-[11px] text-text-faint">→ {d.next_step}</div>
              )}
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}

/** Wired to approvals.py (US3). Approve / reject move the card and the strategy state. Rendered
 * only for a user whose role can decide (the API enforces it; a 403 surfaces inline). */
export function ApprovalQueue() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["org-approvals", "pending"],
    queryFn: () => api.orgApprovals("pending"),
    refetchInterval: 8_000,
  });
  const [error, setError] = useState<string | null>(null);
  const [rejectId, setRejectId] = useState<string | null>(null);
  const [reason, setReason] = useState("");

  const decide = useMutation({
    mutationFn: (v: { id: string; action: "approve" | "reject"; reason?: string }) =>
      v.action === "approve" ? api.orgApprove(v.id) : api.orgReject(v.id, v.reason ?? ""),
    onSuccess: () => {
      setError(null);
      setRejectId(null);
      setReason("");
      queryClient.invalidateQueries({ queryKey: ["org-approvals"] });
    },
    onError: (e: unknown) => setError(e instanceof Error ? e.message : "decision failed"),
  });

  return (
    <Card eyebrow="Human-in-the-loop" title="Approvals" density="dense">
      {isLoading ? (
        <div className="h-10 animate-pulse rounded-lg bg-bg" />
      ) : !data || data.length === 0 ? (
        <p className={NONE}>Nothing awaiting approval.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {data.map((a) => (
            <li key={a.id} className="rounded-lg border border-card-edge p-2">
              <div className="text-xs font-medium">strategy {a.strategy_id.slice(0, 8)}</div>
              <div className={NONE}>opened {a.created_at ?? "—"}</div>
              {rejectId === a.id ? (
                <div className="mt-1.5 flex flex-col gap-1.5">
                  <textarea
                    className="w-full rounded-md border border-card-edge bg-bg p-1.5 text-xs"
                    placeholder="Reason (required)"
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                  />
                  <div className="flex gap-1.5">
                    <button
                      className="rounded-md bg-destructive/10 px-2 py-1 text-[11px] text-destructive disabled:opacity-50"
                      disabled={!reason.trim() || decide.isPending}
                      onClick={() =>
                        decide.mutate({ id: a.id, action: "reject", reason })
                      }
                    >
                      Confirm reject
                    </button>
                    <button
                      className="rounded-md border border-card-edge px-2 py-1 text-[11px]"
                      onClick={() => setRejectId(null)}
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <div className="mt-1.5 flex gap-1.5">
                  <button
                    className="rounded-md bg-primary px-2 py-1 text-[11px] text-primary-foreground disabled:opacity-50"
                    disabled={decide.isPending}
                    onClick={() => decide.mutate({ id: a.id, action: "approve" })}
                  >
                    Approve → Paper
                  </button>
                  <button
                    className="rounded-md border border-card-edge px-2 py-1 text-[11px]"
                    onClick={() => setRejectId(a.id)}
                  >
                    Reject
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {error && <p className="mt-2 text-[11px] text-destructive">{error}</p>}
    </Card>
  );
}

/** GET /organization/attention -- cross-run stalled runs, blocked/escalated tasks, unresolved
 * escalated decisions. */
export function AttentionQueue() {
  const { data, isLoading } = useQuery({
    queryKey: ["org-attention"],
    queryFn: api.orgAttention,
    refetchInterval: 8_000,
  });
  return (
    <Card eyebrow="Needs a human" title="Attention" density="dense">
      {isLoading ? (
        <div className="h-10 animate-pulse rounded-lg bg-bg" />
      ) : !data ||
        (data.stalled_runs.length === 0 &&
          data.blocked_tasks.length === 0 &&
          data.escalated_decisions.length === 0) ? (
        <p className={NONE}>Nothing needs attention.</p>
      ) : (
        <div className="flex flex-col gap-2 text-xs">
          {data.stalled_runs.map((r) => (
            <div key={r.run_id} className="rounded-lg border border-card-edge p-2">
              <Badge variant="destructive">stalled</Badge> {r.objective}
            </div>
          ))}
          {data.blocked_tasks.map((t) => (
            <div key={t.task_id} className="rounded-lg border border-card-edge p-2">
              <Badge variant="outline">{t.status}</Badge> {t.capability} —{" "}
              <span className="text-text-muted">{t.blocked_reason ?? "no reason given"}</span>
            </div>
          ))}
          {data.escalated_decisions.map((d) => (
            <div key={d.decision_id} className="rounded-lg border border-card-edge p-2">
              <Badge variant="destructive">→ {d.escalated_to_role}</Badge> {d.summary}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

/** FR-086: the plan's tasks grouped by the assigned agent's department is not on the plan
 * payload, so this groups by capability family as a stable, backend-derived proxy. */
export function DepartmentView({ tasks }: { tasks: OrgPlannedTask[] | OrgTask[] }) {
  const groups = new Map<string, (OrgPlannedTask | OrgTask)[]>();
  for (const t of tasks) {
    const family = t.capability.split("_")[0] || "other";
    groups.set(family, [...(groups.get(family) ?? []), t]);
  }
  return (
    <Card eyebrow="Organisation" title="By department" density="dense">
      {groups.size === 0 ? (
        <p className={NONE}>No plan yet.</p>
      ) : (
        <div className="flex flex-col gap-2">
          {[...groups.entries()].map(([family, ts]) => (
            <div key={family}>
              <div className="text-[11px] font-semibold uppercase tracking-wide text-text-muted">
                {family}
              </div>
              <ul className="mt-0.5 flex flex-col gap-0.5">
                {ts.map((t) => (
                  <li key={t.task_id} className="text-xs">
                    <span className={cn("mr-1.5 inline-block h-1.5 w-1.5 rounded-full", dot(t.status))} />
                    {t.assigned_agent} · {t.capability} · {t.status}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

export function ArtefactList({ artefacts }: { artefacts: OrgArtefact[] }) {
  return (
    <Card eyebrow="Outputs" title="Result artefacts" density="dense">
      {artefacts.length === 0 ? (
        <p className={NONE}>No artefacts produced yet.</p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {artefacts.map((a) => (
            <li key={a.artefact_id} className="rounded-lg border border-card-edge p-2 text-xs">
              <div className="flex items-center gap-2">
                <Badge variant="outline">{a.artefact_type}</Badge>
                <span className="text-text-faint">v{a.version}</span>
                {a.disposition && <span className="text-text-faint">· {a.disposition}</span>}
                {a.coverage && <span className="text-text-faint">· {a.coverage}</span>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function dot(status: string): string {
  if (["completed", "satisfied"].includes(status)) return "bg-emerald-500";
  if (["failed", "blocked", "cancelled"].includes(status)) return "bg-destructive";
  if (["running"].includes(status)) return "bg-sky-500";
  if (status.startsWith("waiting")) return "bg-amber-500";
  return "bg-text-faint";
}
