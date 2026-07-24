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

  return (
    <RequireAuth>
      <TopBar connected={connected} subtitle="Agent Console" />

      <main className="mx-auto flex w-full max-w-[1440px] flex-1 flex-col gap-4 p-6 sm:p-8">
        <GlassCard eyebrow="Orchestrator" title="Research Cycle">
          <RunControls selectedRunId={effectiveRunId} onSelectRun={setSelectedRunId} />
        </GlassCard>

        <GlassCard eyebrow="LangGraph" title="Live Execution State">
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
        </GlassCard>

        <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
          <GlassCard eyebrow="Reasoning" title="Thought Stream" className="xl:col-span-7">
            <div className="h-[360px]">
              <ThoughtStream messages={logs} connected={connected} />
            </div>
          </GlassCard>

          <GlassCard eyebrow="Hot-swappable" title="Prompt Management" className="xl:col-span-5">
            <PromptManager />
          </GlassCard>
        </div>
      </main>
    </RequireAuth>
  );
}
