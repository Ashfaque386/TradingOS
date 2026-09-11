"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAgentLogStream } from "@/hooks/useAgentLogStream";
import { usePageStatus } from "@/hooks/usePageStatus";
import { Card } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { OrganizationOverview } from "@/components/console";
import { GraphFlowchart } from "@/components/agents/graph-flowchart";
import { ThoughtStream } from "@/components/agents/thought-stream";
import { RunControls } from "@/components/agents/run-controls";
import { HitlPanel } from "@/components/agents/hitl-panel";
import { AgentRegistry } from "@/components/agents/agent-registry";
import { AgentAnalyticsPanel } from "@/components/agents/agent-analytics-panel";

/** US5 (FR-080) + retirement of the old standalone /agents page: this is now the *one*
 * Organization Command Center, home to both the CEO-led org view (the primary tab) and the
 * still-real legacy single-thread graph's own observability (agent enable/disable, execution
 * state, analytics) -- previously split across two separate top-level nav entries ("Agent
 * Console" and "Organization"), which read as two competing, similarly-named consoles rather
 * than one. `/agents` now redirects here (next.config.ts). */
export default function ConsoleHome() {
  const { logs, connected } = useAgentLogStream();
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  usePageStatus("Organization Command Center", connected);

  const topologyQuery = useQuery({ queryKey: ["graph-topology"], queryFn: api.graphTopology });
  const runsQuery = useQuery({ queryKey: ["agent-runs"], queryFn: api.runs, refetchInterval: 5_000 });

  // Defaults to the most recent legacy run until the operator explicitly picks a different one.
  const effectiveRunId = selectedRunId ?? runsQuery.data?.[0]?.run_id ?? null;

  const runDetailQuery = useQuery({
    queryKey: ["agent-run", effectiveRunId],
    queryFn: () => api.run(effectiveRunId!),
    enabled: !!effectiveRunId,
    refetchInterval: (query) => (query.state.data?.status === "Running" ? 4_000 : false),
  });

  return (
    <main className="mx-auto flex w-full max-w-[1440px] flex-1 flex-col gap-4 p-6 sm:p-8">
      <div>
        <h1 className="text-lg font-semibold">Organization Command Center</h1>
        <p className="text-[11px] text-text-faint">
          Live organisation state — every figure is a real backend read, none is hard-coded.
        </p>
      </div>

      <Tabs defaultValue="organization">
        <TabsList>
          <TabsTrigger value="organization">Organization</TabsTrigger>
          <TabsTrigger value="agents">Agents &amp; Legacy Graph</TabsTrigger>
          <TabsTrigger value="analytics">Analytics</TabsTrigger>
        </TabsList>

        <TabsContent value="organization" className="mt-4">
          <OrganizationOverview />
        </TabsContent>

        <TabsContent value="agents" className="mt-4 flex flex-col gap-4">
          <Card eyebrow="Per-agent control" title="Agent Registry">
            <p className="mb-3 text-[11px] text-text-faint">
              The real, durable enable/disable state for every currently-shipped agent (ADR 11,
              Phase_1_Architecture_Decision_Record.md). A disabled pipeline node halts the next
              run before its real logic executes; a disabled scheduled agent is skipped at its
              next trigger. Rows marked &ldquo;not yet enforced&rdquo; store real state but no
              call site checks it yet.
            </p>
            <AgentRegistry />
          </Card>

          <Card eyebrow="LangGraph" title="Legacy Graph — Live Execution State">
            <p className="mb-3 text-[11px] text-text-faint">
              The single-thread research pipeline (<code>trigger_research()</code>) that
              predates the CEO-led organisation model — still real, still used by the composite{" "}
              <code>strategy_research</code> org-task capability under the hood. Starting new
              work here has moved to the Organization tab&apos;s &ldquo;New objective&rdquo;
              panel; this view is for observing/retrying a run&apos;s own execution state.
            </p>
            <RunControls selectedRunId={effectiveRunId} onSelectRun={setSelectedRunId} />
            {topologyQuery.data ? (
              <GraphFlowchart topology={topologyQuery.data} run={runDetailQuery.data ?? null} />
            ) : (
              <div className="h-24 animate-pulse rounded-xl bg-bg" />
            )}
            <p className="mt-3 text-[11px] text-text-faint">
              {topologyQuery.data
                ? `${topologyQuery.data.nodes.length} nodes, ${topologyQuery.data.edges.length} edges`
                : "Loading topology"}{" "}
              introspected live from the compiled graph (GET /agents/graph), not hand-drawn.
            </p>
            <HitlPanel run={runDetailQuery.data ?? null} />
          </Card>

          <Card eyebrow="Reasoning" title="Thought Stream">
            <div className="h-[420px]">
              <ThoughtStream messages={logs} connected={connected} />
            </div>
          </Card>
        </TabsContent>

        <TabsContent value="analytics" className="mt-4">
          <AgentAnalyticsPanel />
        </TabsContent>
      </Tabs>
    </main>
  );
}
