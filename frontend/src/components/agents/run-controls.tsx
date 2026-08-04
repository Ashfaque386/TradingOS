"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { Gated } from "@/components/ui/gated";
import { Button } from "@/components/ui/button";

const STATUS_STYLES: Record<string, string> = {
  Running: "text-brand-via",
  Completed: "text-up",
  Failed: "text-down",
  // REL-019 E19.2 (ADR 11): a halted run is a deliberate stop (a disabled agent's real logic
  // never ran), not a failure -- its own color keeps it visually distinct from Failed.
  Halted: "text-warn",
};

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

  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
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

      <div className="flex items-center gap-1.5 overflow-x-auto">
        {(runsQuery.data ?? []).length === 0 ? (
          <span className="text-[11px] text-text-faint">No runs yet</span>
        ) : (
          runsQuery.data!.map((run) => (
            <button
              key={run.run_id}
              onClick={() => onSelectRun(run.run_id)}
              className={cn(
                "shrink-0 rounded-lg border px-2.5 py-1.5 text-left transition-colors",
                selectedRunId === run.run_id
                  ? "border-text-faint bg-panel"
                  : "border-card-edge bg-bg hover:bg-panel",
              )}
            >
              <div className="font-mono-tabular text-[10px] text-text-dim">
                {new Date(run.started_at).toLocaleTimeString("en-IN", { hour12: false })}
              </div>
              <div className={cn("text-[10px] font-medium", STATUS_STYLES[run.status] ?? "text-text-dim")}>
                {run.status}
              </div>
            </button>
          ))
        )}
      </div>
    </div>
  );
}
