"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Check, RotateCcw, X } from "lucide-react";
import { api } from "@/lib/api";
import { Gated } from "@/components/ui/gated";
import type { AgentRunDetail } from "@/lib/api";

/** REL-011 E11.4b: retry/approve/reject for the Orchestrator HITL endpoints (REL-010 E10.8d) --
 * mounted inside the Agent Console's run-detail view (app/agents/page.tsx), next to the
 * read-only GraphFlowchart/ThoughtStream this run detail already renders. */
export function HitlPanel({ run }: { run: AgentRunDetail | null }) {
  const queryClient = useQueryClient();
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");

  const retry = useMutation({
    mutationFn: (runId: string) => api.retryRun(runId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["agent-runs"] }),
  });

  const approve = useMutation({
    mutationFn: (runId: string) => api.approveRun(runId),
    onSuccess: (_res, runId) =>
      queryClient.invalidateQueries({ queryKey: ["agent-run", runId] }),
  });

  const reject = useMutation({
    mutationFn: ({ runId, reason: r }: { runId: string; reason: string }) =>
      api.rejectRun(runId, r),
    onSuccess: (_res, { runId }) => {
      queryClient.invalidateQueries({ queryKey: ["agent-run", runId] });
      setRejecting(false);
      setReason("");
    },
  });

  if (!run) return null;

  const canRetry = run.status === "Failed";
  const canDecide = run.status === "Completed" && !run.human_decision;

  if (!canRetry && !canDecide && !run.human_decision) return null;

  return (
    <Gated permission="manageHitl">
      <div className="mt-3 rounded-xl border border-white/5 bg-black/20 p-3.5">
        <div className="mb-2 text-[10px] uppercase tracking-wider text-zinc-500">
          Human-in-the-Loop
        </div>

        {run.human_decision && (
          <p
            data-testid="hitl-decision-recorded"
            className="text-[11px] text-zinc-400"
          >
            Decision recorded: <span className="font-medium text-zinc-200">{run.human_decision}</span>
          </p>
        )}

        {canRetry && (
          <button
            onClick={() => retry.mutate(run.run_id)}
            disabled={retry.isPending}
            className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-[11px] font-medium text-zinc-300 transition hover:bg-white/10 disabled:opacity-50"
          >
            <RotateCcw className="h-3 w-3" />
            {retry.isPending ? "Retrying…" : "Retry Failed Run"}
          </button>
        )}

        {canDecide && (
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => approve.mutate(run.run_id)}
              disabled={approve.isPending}
              className="flex items-center gap-1.5 rounded-lg bg-emerald-500/90 px-3 py-1.5 text-[11px] font-semibold text-black transition hover:bg-emerald-400 disabled:opacity-50"
            >
              <Check className="h-3 w-3" /> Approve
            </button>
            {!rejecting ? (
              <button
                onClick={() => setRejecting(true)}
                className="flex items-center gap-1.5 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-1.5 text-[11px] font-medium text-rose-300 transition hover:bg-rose-500/20"
              >
                <X className="h-3 w-3" /> Reject
              </button>
            ) : (
              <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row">
                <input
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="Reason for rejection"
                  className="min-w-[200px] rounded-md border border-white/10 bg-black/30 px-2 py-1.5 text-[11px] text-zinc-200 placeholder:text-zinc-600"
                />
                <div className="flex gap-2">
                  <button
                    onClick={() => setRejecting(false)}
                    className="rounded-lg border border-white/10 px-2.5 py-1.5 text-[11px] text-zinc-400 hover:bg-white/5"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={() => reject.mutate({ runId: run.run_id, reason })}
                    disabled={!reason.trim() || reject.isPending}
                    className="rounded-lg bg-rose-500/90 px-2.5 py-1.5 text-[11px] font-semibold text-black transition hover:bg-rose-400 disabled:opacity-40"
                  >
                    {reject.isPending ? "Rejecting…" : "Confirm reject"}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </Gated>
  );
}
