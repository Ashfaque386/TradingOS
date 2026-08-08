"use client";

import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import type { AgentRunDetail, GraphTopology } from "@/lib/api";

const STRUCTURAL_NODES = new Set(["__start__", "__end__"]);

type NodeState = "pending" | "active" | "completed" | "failed" | "halted";

interface GraphLayout {
  /** Real nodes only (structural start/end excluded), grouped into columns by longest-path
   * distance from __start__ over the DAG-only edge subset (cycle edges removed). */
  layers: string[][];
  /** Edges between two different, real (non-structural) layers -- what actually gets drawn as a
   * connector between columns. */
  forwardEdges: { source: string; target: string; conditional: boolean; sourceLayer: number; targetLayer: number }[];
  /** Edges whose target already has an assigned layer <= its source's layer -- a real cycle
   * (e.g. a validator retry loop), rendered as a badge on the source node rather than a second
   * box, since drawing a literal backward arrow across columns would need real path routing for
   * a case this pipeline only ever uses for retries. */
  backEdges: Map<string, string[]>;
  layerOf: Map<string, number>;
}

/** Longest-path layered layout over the real fetched topology -- replaces the previous
 * single-path chain walk, which silently dropped every node except the first branch found at any
 * fork (real, previously-undetected bug: a topology with genuine parallel branches would render
 * an incomplete graph). Cycles (the python_validator retry loop) are detected via DFS
 * back-edge detection and excluded from layering, not hardcoded to one node pair. */
function layoutGraph(topology: GraphTopology): GraphLayout {
  const outgoing = new Map<string, { target: string; conditional: boolean }[]>();
  for (const edge of topology.edges) {
    if (!outgoing.has(edge.source)) outgoing.set(edge.source, []);
    outgoing.get(edge.source)!.push({ target: edge.target, conditional: edge.conditional });
  }

  // DFS back-edge detection: an edge to a node currently on the recursion stack is a cycle.
  const backEdgeSet = new Set<string>();
  const onStack = new Set<string>();
  const visited = new Set<string>();
  function dfs(node: string) {
    visited.add(node);
    onStack.add(node);
    for (const { target } of outgoing.get(node) ?? []) {
      const key = `${node}->${target}`;
      if (onStack.has(target)) {
        backEdgeSet.add(key);
      } else if (!visited.has(target)) {
        dfs(target);
      }
    }
    onStack.delete(node);
  }
  if (topology.nodes.some((n) => n.id === "__start__")) dfs("__start__");

  // Longest-path layering over the DAG-only subgraph (back edges excluded) via a topological
  // Kahn's-algorithm pass, then relaxing each forward edge in topological order.
  const dagOutgoing = new Map<string, string[]>();
  const inDegree = new Map<string, number>();
  for (const n of topology.nodes) inDegree.set(n.id, 0);
  for (const edge of topology.edges) {
    if (backEdgeSet.has(`${edge.source}->${edge.target}`)) continue;
    if (!dagOutgoing.has(edge.source)) dagOutgoing.set(edge.source, []);
    dagOutgoing.get(edge.source)!.push(edge.target);
    inDegree.set(edge.target, (inDegree.get(edge.target) ?? 0) + 1);
  }

  const queue = [...inDegree.entries()].filter(([, d]) => d === 0).map(([id]) => id);
  const topoOrder: string[] = [];
  const rawLayer = new Map<string, number>();
  for (const id of queue) rawLayer.set(id, 0);
  while (queue.length > 0) {
    const node = queue.shift()!;
    topoOrder.push(node);
    for (const target of dagOutgoing.get(node) ?? []) {
      rawLayer.set(target, Math.max(rawLayer.get(target) ?? 0, (rawLayer.get(node) ?? 0) + 1));
      const remaining = (inDegree.get(target) ?? 0) - 1;
      inDegree.set(target, remaining);
      if (remaining === 0) queue.push(target);
    }
  }

  // Compact layer numbers to only the real (non-structural) nodes, starting at 0.
  const realLayerValues = [...rawLayer.entries()]
    .filter(([id]) => !STRUCTURAL_NODES.has(id))
    .map(([, l]) => l);
  const distinctLayers = [...new Set(realLayerValues)].sort((a, b) => a - b);
  const compact = new Map(distinctLayers.map((l, i) => [l, i]));

  const layerOf = new Map<string, number>();
  const layers: string[][] = distinctLayers.map(() => []);
  for (const n of topology.nodes) {
    if (STRUCTURAL_NODES.has(n.id)) continue;
    const raw = rawLayer.get(n.id);
    if (raw === undefined) continue; // unreachable from __start__ over DAG edges
    const layer = compact.get(raw)!;
    layerOf.set(n.id, layer);
    layers[layer].push(n.id);
  }

  const forwardEdges: GraphLayout["forwardEdges"] = [];
  const backEdges = new Map<string, string[]>();
  for (const edge of topology.edges) {
    if (STRUCTURAL_NODES.has(edge.source) || STRUCTURAL_NODES.has(edge.target)) continue;
    if (backEdgeSet.has(`${edge.source}->${edge.target}`)) {
      if (!backEdges.has(edge.source)) backEdges.set(edge.source, []);
      backEdges.get(edge.source)!.push(edge.target);
      continue;
    }
    const sourceLayer = layerOf.get(edge.source);
    const targetLayer = layerOf.get(edge.target);
    if (sourceLayer === undefined || targetLayer === undefined) continue;
    forwardEdges.push({ source: edge.source, target: edge.target, conditional: edge.conditional, sourceLayer, targetLayer });
  }

  return { layers, forwardEdges, backEdges, layerOf };
}

function nodeLabel(id: string): string {
  return id
    .split("_")
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(" ");
}

const STATE_STYLES: Record<NodeState, string> = {
  pending: "border-card-edge bg-bg text-text-faint",
  active: "border-brand-via/50 bg-brand-via/10 text-brand-via shadow-[0_0_24px_rgba(255,92,122,0.35)]",
  completed: "border-up/40 bg-up/[0.08] text-up",
  failed: "border-down/40 bg-down/[0.08] text-down",
  // REL-019 E19.2 (ADR 11): the halted node itself never gets its own child AgentRun row (its
  // real logic never ran, so there's nothing to persist) -- inferred as a frontier node the same
  // way "active" is, distinguished visually since it's a deliberate stop, not progress.
  halted: "border-warn/40 bg-warn/[0.08] text-warn",
};

export function GraphFlowchart({
  topology,
  run,
}: {
  topology: GraphTopology;
  run: AgentRunDetail | null;
}) {
  const { layers, forwardEdges, backEdges, layerOf } = layoutGraph(topology);

  const completedIds = new Set((run?.nodes ?? []).map((n) => n.agent_name));
  const failedIds = new Set(
    (run?.nodes ?? []).filter((n) => n.status === "Failed").map((n) => n.agent_name),
  );

  // A node is the "frontier" -- the real next step to run -- if at least one of its DAG
  // predecessors is completed and it isn't itself completed/failed yet. Generalizes the old
  // single-index "how far along the chain" tracker to a graph with real parallel branches:
  // multiple frontier nodes can be active at once if the topology genuinely forks.
  const predecessorsOf = new Map<string, string[]>();
  for (const e of forwardEdges) {
    if (!predecessorsOf.has(e.target)) predecessorsOf.set(e.target, []);
    predecessorsOf.get(e.target)!.push(e.source);
  }
  const isFrontier = (id: string): boolean => {
    if (completedIds.has(id) || failedIds.has(id)) return false;
    const layer = layerOf.get(id) ?? 0;
    if (layer === 0) return true; // first real layer, no predecessors needed
    const preds = predecessorsOf.get(id) ?? [];
    return preds.some((p) => completedIds.has(p));
  };

  const stateFor = (id: string): NodeState => {
    if (failedIds.has(id)) return "failed";
    if (completedIds.has(id)) return "completed";
    if (run?.status === "Running" && isFrontier(id)) return "active";
    if (run?.status === "Halted" && isFrontier(id)) return "halted";
    return "pending";
  };

  return (
    <div className="overflow-x-auto pb-2">
      <div className="flex min-w-max items-stretch gap-1.5">
        {layers.map((columnIds, colIndex) => (
          <div key={colIndex} className="flex items-center gap-1.5">
            <div className="flex flex-col justify-center gap-2">
              {columnIds.map((id) => {
                const state = stateFor(id);
                const retries = backEdges.get(id);
                return (
                  <motion.div
                    key={id}
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: colIndex * 0.05 }}
                    className={cn(
                      "relative flex min-w-[132px] flex-col items-center gap-1 rounded-xl border px-4 py-3 text-center transition-colors duration-500",
                      STATE_STYLES[state],
                    )}
                  >
                    {state === "active" && (
                      <span className="absolute -top-1.5 -right-1.5 h-2.5 w-2.5 animate-pulse-glow rounded-full bg-brand-via" />
                    )}
                    <span className="text-[11px] font-medium leading-tight">{nodeLabel(id)}</span>
                    <span className="text-[9px] uppercase tracking-wider opacity-60">{state}</span>
                    {retries && retries.length > 0 && (
                      <span className="absolute -bottom-2 rounded-full border border-warn/30 bg-warn/10 px-1.5 py-0.5 text-[8px] font-medium uppercase tracking-wider text-warn">
                        ↺ retry → {retries.map(nodeLabel).join(", ")}
                      </span>
                    )}
                  </motion.div>
                );
              })}
            </div>
            {colIndex < layers.length - 1 && (
              <div className="flex flex-col justify-center gap-1">
                {forwardEdges
                  .filter((e) => e.sourceLayer === colIndex && e.targetLayer === colIndex + 1)
                  .map((e) => (
                    <div key={`${e.source}->${e.target}`} className="flex items-center gap-1">
                      <div
                        className={cn(
                          "h-px w-6 shrink-0 transition-colors duration-500",
                          e.conditional ? "border-t border-dashed border-card-edge bg-transparent" : "bg-card-edge",
                          completedIds.has(e.source) && "bg-up/40 border-up/40",
                        )}
                      />
                    </div>
                  ))}
              </div>
            )}
          </div>
        ))}
        {/* Skip-layer edges (span more than one column) -- rare for this pipeline's real
            topology, surfaced as a compact label instead of a routed multi-column line. */}
        {forwardEdges
          .filter((e) => e.targetLayer > e.sourceLayer + 1)
          .map((e) => (
            <span
              key={`skip-${e.source}->${e.target}`}
              className="self-start rounded-full border border-card-edge bg-bg px-2 py-1 text-[9px] text-text-faint"
            >
              {nodeLabel(e.source)} ⇒ {nodeLabel(e.target)}
            </span>
          ))}
      </div>
    </div>
  );
}
