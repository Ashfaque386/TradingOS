"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Ban, CircleCheck, ShieldAlert } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Gated } from "@/components/ui/gated";
import { Button } from "@/components/ui/button";
import type { AgentControlEntry } from "@/lib/api";

const KIND_LABEL: Record<AgentControlEntry["kind"], string> = {
  graph_node: "Pipeline node",
  scheduled: "Scheduled job",
  registry_only: "Registry only",
};

/** REL-019 E19.2/E19.3 (ADR 11): per-agent registry replacing the Agent Console's previous
 * "one shared run-level status" view. `enforced` (src/agents/control.py::KNOWN_AGENTS) is shown
 * honestly per-agent -- a `registry_only` row's toggle still writes real, durable state, it just
 * doesn't stop anything yet, and the UI says so rather than implying uniform enforcement. */
export function AgentRegistry() {
  const queryClient = useQueryClient();
  const [pendingDisable, setPendingDisable] = useState<string | null>(null);
  const [reason, setReason] = useState("");

  const registryQuery = useQuery({
    queryKey: ["agent-control"],
    queryFn: api.agentControlList,
    refetchInterval: 10_000,
  });

  const setEnabled = useMutation({
    mutationFn: ({ agentName, enabled, reason: r }: { agentName: string; enabled: boolean; reason: string | null }) =>
      api.setAgentEnabled(agentName, enabled, r),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agent-control"] });
      setPendingDisable(null);
      setReason("");
    },
  });

  if (registryQuery.isLoading) {
    return <div className="h-40 animate-pulse rounded-xl bg-bg" />;
  }

  const entries = registryQuery.data ?? [];

  return (
    <div className="flex flex-col gap-1.5">
      {entries.map((agent) => {
        const isPendingThis = setEnabled.isPending && setEnabled.variables?.agentName === agent.agent_name;
        return (
          <div
            key={agent.agent_name}
            className="flex items-center justify-between gap-3 rounded-lg border border-card-edge bg-bg px-3 py-row-dense"
          >
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5">
                <span className="truncate text-[11px] font-medium text-text">
                  {agent.display_name}
                </span>
                <span className="shrink-0 font-mono-tabular text-[9px] text-text-faint">
                  {agent.agent_id}
                </span>
              </div>
              <div className="flex items-center gap-1.5 text-[10px] text-text-faint">
                <span>{KIND_LABEL[agent.kind]}</span>
                {!agent.enforced && (
                  <span className="flex items-center gap-0.5 text-warn/80">
                    <ShieldAlert className="h-2.5 w-2.5" /> not yet enforced
                  </span>
                )}
                {!agent.enabled && agent.reason && (
                  <span className="truncate text-down/80">— {agent.reason}</span>
                )}
              </div>
            </div>

            <Gated
              permission="manageAgentControl"
              fallback={
                <span
                  className={cn(
                    "flex items-center gap-1 text-[10px] font-medium",
                    agent.enabled ? "text-up" : "text-down",
                  )}
                >
                  {agent.enabled ? <CircleCheck className="h-3 w-3" /> : <Ban className="h-3 w-3" />}
                  {agent.enabled ? "Enabled" : "Disabled"}
                </span>
              }
            >
              {agent.enabled ? (
                pendingDisable === agent.agent_name ? (
                  <div className="flex items-center gap-1.5">
                    <input
                      value={reason}
                      onChange={(e) => setReason(e.target.value)}
                      placeholder="Reason"
                      autoFocus
                      className="w-28 rounded-md border border-card-edge bg-panel px-1.5 py-1 text-[10px] text-text placeholder:text-text-faint"
                    />
                    <Button
                      onClick={() =>
                        setEnabled.mutate({ agentName: agent.agent_name, enabled: false, reason: reason || null })
                      }
                      disabled={!reason.trim() || isPendingThis}
                      variant="destructive"
                      className="px-2 py-1 text-[10px]"
                    >
                      Confirm
                    </Button>
                    <Button onClick={() => setPendingDisable(null)} variant="secondary" className="px-2 py-1 text-[10px]">
                      Cancel
                    </Button>
                  </div>
                ) : (
                  <Button
                    onClick={() => {
                      setPendingDisable(agent.agent_name);
                      setReason("");
                    }}
                    variant="destructive"
                    className="shrink-0 px-2 py-1 text-[10px]"
                  >
                    <Ban className="h-3 w-3" /> Disable
                  </Button>
                )
              ) : (
                <Button
                  onClick={() =>
                    setEnabled.mutate({ agentName: agent.agent_name, enabled: true, reason: null })
                  }
                  disabled={isPendingThis}
                  className="shrink-0 px-2 py-1 text-[10px]"
                >
                  <CircleCheck className="h-3 w-3" /> {isPendingThis ? "Enabling…" : "Enable"}
                </Button>
              )}
            </Gated>
          </div>
        );
      })}
    </div>
  );
}
