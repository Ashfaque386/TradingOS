"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { useState } from "react";
import { Check, Pause, Play, RotateCcw, Square, X } from "lucide-react";
import { api } from "@/lib/api";
import { Gated } from "@/components/ui/gated";
import { Button } from "@/components/ui/button";
import { slideUp } from "@/lib/motion";
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

  // REL-080: pause/resume have been real, tested backend endpoints since REL-060 but had no UI
  // anywhere -- a stuck run (e.g. its driving thread died with the app container mid-run, the
  // real case found investigating a user report) had no visible way to track, pause, or stop.
  // Cancel is a hard stop for exactly that dead-thread case; see the backend endpoint's own
  // docstring for why it's safe even in the rare case the thread turns out to still be alive.
  const pause = useMutation({
    mutationFn: (runId: string) => api.pauseRun(runId),
    onSuccess: (_res, runId) => queryClient.invalidateQueries({ queryKey: ["agent-run", runId] }),
  });
  const resume = useMutation({
    mutationFn: (runId: string) => api.resumeRun(runId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["agent-runs"] }),
  });
  const cancel = useMutation({
    mutationFn: (runId: string) => api.cancelRun(runId),
    onSuccess: (_res, runId) => {
      queryClient.invalidateQueries({ queryKey: ["agent-run", runId] });
      queryClient.invalidateQueries({ queryKey: ["agent-runs"] });
    },
  });

  if (!run) return null;

  const canRetry = run.status === "Failed";
  const canDecide = run.status === "Completed" && !run.human_decision;
  const canPause = run.status === "Running";
  const canResume = run.status === "Paused";
  const canCancel = run.status === "Running" || run.status === "Paused";

  if (!canRetry && !canDecide && !canPause && !canResume && !run.human_decision) return null;

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

        {(canPause || canResume || canCancel) && (
          <div className="flex flex-wrap items-center gap-2">
            {canPause && (
              <Button
                onClick={() => pause.mutate(run.run_id)}
                disabled={pause.isPending}
                variant="secondary"
                className="px-3 py-1.5 text-[11px]"
              >
                <Pause className="h-3 w-3" />
                {pause.isPending ? "Pausing…" : "Pause"}
              </Button>
            )}
            {canResume && (
              <Button
                onClick={() => resume.mutate(run.run_id)}
                disabled={resume.isPending}
                className="px-3 py-1.5 text-[11px]"
              >
                <Play className="h-3 w-3" />
                {resume.isPending ? "Resuming…" : "Resume"}
              </Button>
            )}
            {canCancel && (
              <Button
                onClick={() => cancel.mutate(run.run_id)}
                disabled={cancel.isPending}
                variant="destructive"
                className="px-3 py-1.5 text-[11px]"
              >
                <Square className="h-3 w-3" />
                {cancel.isPending ? "Cancelling…" : "Cancel Run"}
              </Button>
            )}
          </div>
        )}
        {pause.isSuccess && !pause.isPending && run.status === "Running" && (
          <p className="mt-2 text-[11px] text-text-faint">
            Pause requested — takes effect once the run reaches its next checkpoint.
          </p>
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
            <AnimatePresence initial={false}>
              {!rejecting ? (
                <Button
                  key="reject-trigger"
                  onClick={() => setRejecting(true)}
                  variant="destructive"
                  className="px-3 py-1.5 text-[11px]"
                >
                  <X className="h-3 w-3" /> Reject
                </Button>
              ) : (
                <motion.div
                  key="reject-form"
                  initial="hidden"
                  animate="visible"
                  exit="exit"
                  variants={slideUp}
                  className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row"
                >
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
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )}
      </div>
    </Gated>
  );
}
