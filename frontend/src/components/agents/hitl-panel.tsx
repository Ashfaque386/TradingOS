"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Check, RotateCcw, X } from "lucide-react";
import { api } from "@/lib/api";
import { Gated } from "@/components/ui/gated";
import { Button } from "@/components/ui/button";
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
      <div className="mt-3 rounded-xl border border-card-edge bg-bg p-3.5">
        <div className="mb-2 text-[10px] uppercase tracking-wider text-text-faint">
          Human-in-the-Loop
        </div>

        {run.human_decision && (
          <p
            data-testid="hitl-decision-recorded"
            className="text-[11px] text-text-dim"
          >
            Decision recorded: <span className="font-medium text-text">{run.human_decision}</span>
          </p>
        )}

        {canRetry && (
          <Button
            onClick={() => retry.mutate(run.run_id)}
            disabled={retry.isPending}
            variant="secondary"
            className="px-3 py-1.5 text-[11px]"
          >
            <RotateCcw className="h-3 w-3" />
            {retry.isPending ? "Retrying…" : "Retry Failed Run"}
          </Button>
        )}

        {canDecide && (
          <div className="flex flex-wrap items-center gap-2">
            <Button
              onClick={() => approve.mutate(run.run_id)}
              disabled={approve.isPending}
              className="px-3 py-1.5 text-[11px]"
            >
              <Check className="h-3 w-3" /> Approve
            </Button>
            {!rejecting ? (
              <Button
                onClick={() => setRejecting(true)}
                variant="destructive"
                className="px-3 py-1.5 text-[11px]"
              >
                <X className="h-3 w-3" /> Reject
              </Button>
            ) : (
              <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row">
                <input
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="Reason for rejection"
                  className="min-w-[200px] rounded-md border border-card-edge bg-panel px-2 py-1.5 text-[11px] text-text placeholder:text-text-faint"
                />
                <div className="flex gap-2">
                  <Button onClick={() => setRejecting(false)} variant="secondary" className="px-2.5 py-1.5 text-[11px]">
                    Cancel
                  </Button>
                  <Button
                    onClick={() => reject.mutate({ runId: run.run_id, reason })}
                    disabled={!reason.trim() || reject.isPending}
                    variant="destructive"
                    className="px-2.5 py-1.5 text-[11px]"
                  >
                    {reject.isPending ? "Rejecting…" : "Confirm reject"}
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </Gated>
  );
}
