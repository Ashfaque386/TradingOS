"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { useAgentLogStream } from "@/hooks/useAgentLogStream";
import { RequireAuth } from "@/lib/auth";
import { TopBar } from "@/components/layout/top-bar";
import { GlassCard } from "@/components/ui/glass-card";
import { GraphFlowchart } from "@/components/agents/graph-flowchart";
import { ThoughtStream } from "@/components/agents/thought-stream";
import { PromptManager } from "@/components/agents/prompt-manager";
import { RunControls } from "@/components/agents/run-controls";
import { HitlPanel } from "@/components/agents/hitl-panel";
import { GridWorkspace, type GridPanel } from "@/components/layout/grid-workspace";

export default function AgentConsole() {
  const { logs, connected } = useAgentLogStream();
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  const topologyQuery = useQuery({ queryKey: ["graph-topology"], queryFn: api.graphTopology });
  const runsQuery = useQuery({ queryKey: ["agent-runs"], queryFn: api.runs, refetchInterval: 5_000 });

  // Defaults to the most recent run until the operator explicitly picks a different one --
  // derived directly from query data rather than mirrored into state via an effect.
  const effectiveRunId = selectedRunId ?? runsQuery.data?.[0]?.run_id ?? null;

  const runDetailQuery = useQuery({
    queryKey: ["agent-run", effectiveRunId],
    queryFn: () => api.run(effectiveRunId!),
    enabled: !!effectiveRunId,
    refetchInterval: (query) => (query.state.data?.status === "Running" ? 4_000 : false),
  });

  const panels: GridPanel[] = [
    {
      id: "execution-state",
      defaultLayout: { x: 0, y: 0, w: 12, h: 6, minW: 6, minH: 4 },
      node: (
        <GlassCard eyebrow="LangGraph" title="Live Execution State" className="h-full">
          {topologyQuery.data ? (
            <GraphFlowchart topology={topologyQuery.data} run={runDetailQuery.data ?? null} />
          ) : (
            <div className="h-24 animate-pulse rounded-xl bg-white/5" />
          )}
          <p className="mt-3 text-[11px] text-zinc-600">
            5 real nodes (CEO → Market Analyst → Strategy Generator → Code Generator ↺ Validator)
            plus a placeholder terminal node awaiting the Phase 3 backtesting engine. Topology is
            introspected live from the compiled graph, not hand-drawn.
          </p>
          <HitlPanel run={runDetailQuery.data ?? null} />
        </GlassCard>
      ),
    },
    {
      id: "thought-stream",
      defaultLayout: { x: 0, y: 6, w: 7, h: 7, minW: 4, minH: 4 },
      node: (
        <GlassCard eyebrow="Reasoning" title="Thought Stream" className="h-full">
          <div className="h-[360px]">
            <ThoughtStream messages={logs} connected={connected} />
          </div>
        </GlassCard>
      ),
    },
    {
      id: "prompt-manager",
      defaultLayout: { x: 7, y: 6, w: 5, h: 7, minW: 3, minH: 4 },
      node: (
        <GlassCard eyebrow="Hot-swappable" title="Prompt Management" className="h-full">
          <PromptManager />
        </GlassCard>
      ),
    },
  ];

  return (
    <RequireAuth>
      <TopBar connected={connected} subtitle="Agent Console" />

      <main className="mx-auto flex w-full max-w-[1440px] flex-1 flex-col gap-4 p-6 sm:p-8">
        <GlassCard eyebrow="Orchestrator" title="Research Cycle">
          <RunControls selectedRunId={effectiveRunId} onSelectRun={setSelectedRunId} />
        </GlassCard>

        <GridWorkspace storageKey="tradingos:grid:agents" panels={panels} />
      </main>
    </RequireAuth>
  );
}
