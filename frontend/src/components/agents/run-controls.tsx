"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { Gated } from "@/components/ui/gated";

const STATUS_STYLES: Record<string, string> = {
  Running: "text-cyan-300",
  Completed: "text-emerald-300",
  Failed: "text-rose-300",
  // REL-019 E19.2 (ADR 11): a halted run is a deliberate stop (a disabled agent's real logic
  // never ran), not a failure -- its own color keeps it visually distinct from Failed.
  Halted: "text-amber-300",
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
          <button
            onClick={() => trigger.mutate()}
            disabled={trigger.isPending}
            className="flex items-center gap-2 rounded-lg bg-gradient-to-r from-cyan-500 to-purple-500 px-4 py-2 text-xs font-semibold text-black transition hover:brightness-110 disabled:opacity-50"
          >
            <Play className="h-3.5 w-3.5" />
            {trigger.isPending ? "Starting…" : "Trigger Research Cycle"}
          </button>
        </Gated>
        {trigger.isError && (
          <span className="text-[11px] text-rose-400">Failed to start — is the backend up?</span>
        )}
      </div>

      <div className="flex items-center gap-1.5 overflow-x-auto">
        {(runsQuery.data ?? []).length === 0 ? (
          <span className="text-[11px] text-zinc-600">No runs yet</span>
        ) : (
          runsQuery.data!.map((run) => (
            <button
              key={run.run_id}
              onClick={() => onSelectRun(run.run_id)}
              className={cn(
                "shrink-0 rounded-lg border px-2.5 py-1.5 text-left transition-colors",
                selectedRunId === run.run_id
                  ? "border-white/20 bg-white/10"
                  : "border-white/5 bg-black/20 hover:bg-white/5",
              )}
            >
              <div className="font-mono-tabular text-[10px] text-zinc-400">
                {new Date(run.started_at).toLocaleTimeString("en-IN", { hour12: false })}
              </div>
              <div className={cn("text-[10px] font-medium", STATUS_STYLES[run.status] ?? "text-zinc-400")}>
                {run.status}
              </div>
            </button>
          ))
        )}
      </div>
    </div>
  );
}
