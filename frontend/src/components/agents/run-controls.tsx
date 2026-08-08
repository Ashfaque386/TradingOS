"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { Gated } from "@/components/ui/gated";
import { Button } from "@/components/ui/button";
import type { AgentRunSummary } from "@/lib/api";

const STATUS_DOT: Record<string, string> = {
  Running: "bg-brand-via",
  Completed: "bg-up",
  Failed: "bg-down",
  // REL-019 E19.2 (ADR 11): a halted run is a deliberate stop (a disabled agent's real logic
  // never ran), not a failure -- its own color keeps it visually distinct from Failed.
  Halted: "bg-warn",
};

const STATUS_TEXT: Record<string, string> = {
  Running: "text-brand-via",
  Completed: "text-up",
  Failed: "text-down",
  Halted: "text-warn",
};

function relativeTime(iso: string): string {
  const deltaMs = Date.now() - new Date(iso).getTime();
  const minutes = Math.round(deltaMs / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function duration(run: AgentRunSummary): string | null {
  if (!run.ended_at) return null;
  const ms = new Date(run.ended_at).getTime() - new Date(run.started_at).getTime();
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms / 60_000)}m`;
}

export function RunControls({
  selectedRunId,
  onSelectRun,
}: {
  selectedRunId: string | null;
  onSelectRun: (runId: string) => void;
}) {
  const queryClient = useQueryClient();
  const runsQuery = useQuery({
    queryKey: ["agent-runs"],
    queryFn: api.runs,
    refetchInterval: 5_000,
  });

  const trigger = useMutation({
    mutationFn: api.triggerResearch,
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ["agent-runs"] });
      onSelectRun(res.run_id);
    },
  });

  const runs = runsQuery.data ?? [];

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <Gated permission="triggerResearch">
          <Button onClick={() => trigger.mutate()} disabled={trigger.isPending} className="px-4 py-2 text-xs">
            <Play className="h-3.5 w-3.5" />
            {trigger.isPending ? "Starting…" : "Trigger Research Cycle"}
          </Button>
        </Gated>
        {trigger.isError && (
          <span className="text-[11px] text-down">Failed to start — is the backend up?</span>
        )}
      </div>

      {runs.length === 0 ? (
        <p className="text-[11px] text-text-faint">No runs yet.</p>
      ) : (
        <div className="max-h-[280px] overflow-y-auto pr-1">
          <ol className="relative flex flex-col">
            {runs.map((run, i) => {
              const selected = selectedRunId === run.run_id;
              const runDuration = duration(run);
              return (
                <li key={run.run_id} className="relative flex gap-3 pb-3 last:pb-0">
                  {i < runs.length - 1 && (
                    <span className="absolute top-3 left-[5px] h-full w-px bg-card-edge" />
                  )}
                  <span
                    className={cn(
                      "relative z-10 mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full",
                      STATUS_DOT[run.status] ?? "bg-text-faint",
                    )}
                  />
                  <button
                    onClick={() => onSelectRun(run.run_id)}
                    className={cn(
                      "flex flex-1 items-center justify-between gap-3 rounded-lg border px-3 py-2 text-left transition-colors",
                      selected
                        ? "border-text-faint bg-panel"
                        : "border-transparent bg-bg hover:border-card-edge",
                    )}
                  >
                    <div>
                      <div className="flex items-center gap-2">
                        <span className={cn("text-[11px] font-medium", STATUS_TEXT[run.status] ?? "text-text-dim")}>
                          {run.status}
                        </span>
                        {runDuration && (
                          <span className="font-mono-tabular text-[10px] text-text-faint">{runDuration}</span>
                        )}
                      </div>
                      <div className="font-mono-tabular text-[10px] text-text-faint">
                        {new Date(run.started_at).toLocaleTimeString("en-IN", { hour12: false })} ·{" "}
                        {relativeTime(run.started_at)}
                      </div>
                    </div>
                  </button>
                </li>
              );
            })}
          </ol>
        </div>
      )}
    </div>
  );
}
