"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { useAgentLogStream } from "@/hooks/useAgentLogStream";
import { usePageStatus } from "@/hooks/usePageStatus";
import { Card } from "@/components/ui/card";
import { GraphFlowchart } from "@/components/agents/graph-flowchart";
import { ThoughtStream } from "@/components/agents/thought-stream";
import { PromptManager } from "@/components/agents/prompt-manager";
import { RunControls } from "@/components/agents/run-controls";
import { HitlPanel } from "@/components/agents/hitl-panel";
import { AgentRegistry } from "@/components/agents/agent-registry";

/** Phase 2C: fixed premium layout replacing the drag/resize GridWorkspace grid -- a real visual
 * hierarchy (execution state, then registry, then a reasoning/prompts row) instead of manually
 * positioned, user-draggable panels. */
export default function AgentConsole() {
  const { logs, connected } = useAgentLogStream();
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  usePageStatus("Agent Console", connected);

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
    <main className="mx-auto flex w-full max-w-[1440px] flex-1 flex-col gap-4 p-6 sm:p-8">
      <Card eyebrow="Orchestrator" title="Research Cycle">
        <RunControls selectedRunId={effectiveRunId} onSelectRun={setSelectedRunId} />
      </Card>

      <Card eyebrow="LangGraph" title="Live Execution State">
        {topologyQuery.data ? (
          <GraphFlowchart topology={topologyQuery.data} run={runDetailQuery.data ?? null} />
        ) : (
          <div className="h-24 animate-pulse rounded-xl bg-bg" />
        )}
        <p className="mt-3 text-[11px] text-text-faint">
          5 real nodes (CEO → Market Analyst → Strategy Generator → Code Generator ↺ Validator)
          plus a placeholder terminal node awaiting the Phase 3 backtesting engine. Topology is
          introspected live from the compiled graph, not hand-drawn.
        </p>
        <HitlPanel run={runDetailQuery.data ?? null} />
      </Card>

      <Card eyebrow="Per-agent control" title="Agent Registry">
        <p className="mb-3 text-[11px] text-text-faint">
          The real, durable enable/disable state for every currently-shipped agent (ADR 11,
          Phase_1_Architecture_Decision_Record.md). A disabled pipeline node halts the next run
          before its real logic executes; a disabled scheduled agent is skipped at its next
          trigger. Rows marked &ldquo;not yet enforced&rdquo; store real state but no call site
          checks it yet.
        </p>
        <AgentRegistry />
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        <Card eyebrow="Reasoning" title="Thought Stream" className="lg:col-span-7">
          <div className="h-[420px]">
            <ThoughtStream messages={logs} connected={connected} />
          </div>
        </Card>
        <Card eyebrow="Hot-swappable" title="Prompt Management" className="lg:col-span-5">
          <div className="max-h-[420px] overflow-y-auto">
            <PromptManager />
          </div>
        </Card>
      </div>
    </main>
  );
}
