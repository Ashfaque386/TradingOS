"use client";

import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import type { AgentRunDetail, GraphTopology } from "@/lib/api";

const STRUCTURAL_NODES = new Set(["__start__", "__end__"]);

type NodeState = "pending" | "active" | "completed" | "failed" | "halted";

/** Orders the real fetched topology into a linear display chain by walking edges from
 * `__start__`, skipping back-edges (retries) whose target was already visited -- those are
 * rendered as a small "retries" badge on the source node instead of a second box, since this
 * pipeline's only loop is python_validator -> python_code_generator on a failed validation. */
function deriveChain(topology: GraphTopology): { chain: string[]; retryEdges: Set<string> } {
  const outgoing = new Map<string, string[]>();
  for (const edge of topology.edges) {
    if (!outgoing.has(edge.source)) outgoing.set(edge.source, []);
    outgoing.get(edge.source)!.push(edge.target);
  }

  const chain: string[] = [];
  const retryEdges = new Set<string>();
  const visited = new Set<string>();
  let current = "__start__";

  while (current && !visited.has(current)) {
    visited.add(current);
    if (!STRUCTURAL_NODES.has(current)) chain.push(current);

    const nextOptions = (outgoing.get(current) ?? []).filter((n) => !STRUCTURAL_NODES.has(n));
    const unvisitedNext = nextOptions.find((n) => !visited.has(n));

    for (const n of nextOptions) {
      if (visited.has(n)) retryEdges.add(`${current}->${n}`);
    }

    current = unvisitedNext ?? "";
  }

  return { chain, retryEdges };
}

function nodeLabel(id: string): string {
  return id
    .split("_")
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(" ");
}

const STATE_STYLES: Record<NodeState, string> = {
  pending: "border-white/10 bg-white/[0.02] text-zinc-600",
  active: "border-cyan-400/50 bg-cyan-400/10 text-cyan-200 shadow-[0_0_24px_rgba(34,211,238,0.35)]",
  completed: "border-emerald-400/40 bg-emerald-400/[0.08] text-emerald-200",
  failed: "border-rose-400/40 bg-rose-400/[0.08] text-rose-200",
  // REL-019 E19.2 (ADR 11): the halted node itself never gets its own child AgentRun row (its
  // real logic never ran, so there's nothing to persist) -- inferred here as the same
  // next-in-chain position a "Running" state would call "active", distinguished visually since
  // it's a deliberate stop, not progress.
  halted: "border-amber-400/40 bg-amber-400/[0.08] text-amber-200",
};

export function GraphFlowchart({
  topology,
  run,
}: {
  topology: GraphTopology;
  run: AgentRunDetail | null;
}) {
  const { chain, retryEdges } = deriveChain(topology);

  const completedIds = new Set((run?.nodes ?? []).map((n) => n.agent_name));
  const failedIds = new Set((run?.nodes ?? []).filter((n) => n.status === "Failed").map((n) => n.agent_name));
  const lastCompletedIndex = chain.reduce(
    (acc, id, i) => (completedIds.has(id) ? i : acc),
    -1,
  );
  const activeIndex =
    run?.status === "Running" && lastCompletedIndex < chain.length - 1 ? lastCompletedIndex + 1 : -1;
  const haltedIndex =
    run?.status === "Halted" && lastCompletedIndex < chain.length - 1 ? lastCompletedIndex + 1 : -1;

  const stateFor = (id: string, index: number): NodeState => {
    if (failedIds.has(id)) return "failed";
    if (completedIds.has(id)) return "completed";
    if (index === activeIndex) return "active";
    if (index === haltedIndex) return "halted";
    return "pending";
  };

  return (
    <div className="overflow-x-auto pb-2">
      <div className="flex min-w-max items-center gap-1.5">
        {chain.map((id, i) => {
          const state = stateFor(id, i);
          const hasRetry = retryEdges.has(`python_validator->${id}`);
          return (
            <div key={id} className="flex items-center gap-1.5">
              <motion.div
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.05 }}
                className={cn(
                  "relative flex min-w-[132px] flex-col items-center gap-1 rounded-xl border px-4 py-3 text-center transition-colors duration-500",
                  STATE_STYLES[state],
                )}
              >
                {state === "active" && (
                  <span className="absolute -top-1.5 -right-1.5 h-2.5 w-2.5 animate-pulse-glow rounded-full bg-cyan-400" />
                )}
                <span className="text-[11px] font-medium leading-tight">{nodeLabel(id)}</span>
                <span className="text-[9px] uppercase tracking-wider opacity-60">{state}</span>
                {hasRetry && (
                  <span className="absolute -bottom-2 rounded-full border border-amber-400/30 bg-amber-400/10 px-1.5 py-0.5 text-[8px] font-medium uppercase tracking-wider text-amber-300">
                    ↺ retry
                  </span>
                )}
              </motion.div>
              {i < chain.length - 1 && (
                <div
                  className={cn(
                    "h-px w-6 shrink-0 transition-colors duration-500",
                    completedIds.has(id) ? "bg-emerald-400/40" : "bg-white/10",
                  )}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
