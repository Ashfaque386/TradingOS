"use client";

import { motion } from "framer-motion";
import { useQuery } from "@tanstack/react-query";
import { api, type AgentRegistryEntry } from "@/lib/api";
import { agentColor, agentColorStyle } from "@/lib/agentColor";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { staggerContainer, staggerItem } from "@/lib/motion";
import { cn } from "@/lib/utils";

/** spec 002 US12: a live, department-grouped card roster -- real status/current-task/health
 * from `GET /api/v1/agents` (the same `AgentRegistryEntry` list `agent-registry.tsx`'s admin
 * table already consumes; no new endpoint). Additive to that admin enable/disable table, which
 * stays in its own "Agents & Legacy Graph" tab, unaffected. Reused in compact form as the
 * Agent Workspace's in-context switcher strip (US4). */
export function AgentFleet({
  onSelect,
  selectedAgentId,
  compact = false,
}: {
  onSelect?: (agentId: string) => void;
  selectedAgentId?: string;
  compact?: boolean;
}) {
  const registryQuery = useQuery({ queryKey: ["agent-registry"], queryFn: api.agentRegistry });

  if (registryQuery.isLoading)
    return <div className="h-24 animate-pulse rounded-card bg-bg" />;

  const agents = registryQuery.data ?? [];
  if (agents.length === 0)
    return <p className="text-[11px] italic text-text-faint">No agents registered yet.</p>;

  if (compact) {
    return (
      <motion.div
        initial="hidden"
        animate="visible"
        variants={staggerContainer}
        className="flex gap-2 overflow-x-auto pb-1"
      >
        {agents.map((a) => (
          <FleetCard
            key={a.agent_name}
            agent={a}
            compact
            selected={a.agent_name === selectedAgentId || a.agent_id === selectedAgentId}
            onSelect={onSelect}
          />
        ))}
      </motion.div>
    );
  }

  const byDepartment = new Map<string, AgentRegistryEntry[]>();
  for (const a of agents) {
    const list = byDepartment.get(a.department) ?? [];
    list.push(a);
    byDepartment.set(a.department, list);
  }

  return (
    <div className="flex flex-col gap-5">
      {[...byDepartment.entries()].map(([department, deptAgents]) => (
        <div key={department}>
          <div className="mb-2 text-[10px] font-medium uppercase tracking-[0.18em] text-text-faint">
            {department}
          </div>
          <motion.div
            initial="hidden"
            animate="visible"
            variants={staggerContainer}
            className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3"
          >
            {deptAgents.map((a) => (
              <FleetCard
                key={a.agent_name}
                agent={a}
                selected={a.agent_name === selectedAgentId || a.agent_id === selectedAgentId}
                onSelect={onSelect}
              />
            ))}
          </motion.div>
        </div>
      ))}
    </div>
  );
}

function FleetCard({
  agent,
  selected,
  onSelect,
  compact = false,
}: {
  agent: AgentRegistryEntry;
  selected?: boolean;
  onSelect?: (agentId: string) => void;
  compact?: boolean;
}) {
  const statusTone =
    agent.live_status === "Running"
      ? "text-up"
      : agent.health === "degraded" || agent.health === "disabled"
        ? "text-destructive"
        : "text-text-faint";

  return (
    <motion.button
      type="button"
      variants={staggerItem}
      onClick={() => onSelect?.(agent.agent_name)}
      style={agentColorStyle(agent.agent_name)}
      className={cn(
        "text-left",
        compact ? "w-40 shrink-0" : "w-full",
      )}
    >
      <Card
        interactive
        density="dense"
        className={cn(
          "border-l-4 border-l-[var(--agent-color)]",
          selected && "ring-2 ring-[var(--agent-color)]",
        )}
      >
        <div className="flex items-center gap-2">
          <span
            aria-hidden="true"
            className="h-2.5 w-2.5 shrink-0 rounded-full"
            style={{ backgroundColor: agentColor(agent.agent_name) }}
          />
          <span className="truncate text-xs font-semibold text-text">{agent.display_name}</span>
        </div>
        {!compact && (
          <div className="mt-1 truncate text-[11px] text-text-muted">{agent.department}</div>
        )}
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <Badge variant={agent.live_status === "Running" ? "secondary" : "outline"}>
            <span className={statusTone}>{agent.live_status}</span>
          </Badge>
          {!agent.enabled && <Badge variant="destructive">disabled</Badge>}
        </div>
        {!compact && (
          <div className="mt-2 text-[11px] text-text-faint">
            {agent.last_run_status ? `Last: ${agent.last_run_status}` : "No runs yet"}
          </div>
        )}
      </Card>
    </motion.button>
  );
}
