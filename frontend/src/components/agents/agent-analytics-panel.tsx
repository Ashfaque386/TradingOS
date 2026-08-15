"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { AgentSuccessRateTable } from "@/components/agents/agent-success-rate-table";
import { AgentSuccessRateChart } from "@/components/agents/agent-success-rate-chart";
import { AgentRunVolumeChart } from "@/components/agents/agent-run-volume-chart";

const DAY_RANGES = [7, 30, 90] as const;

/** REL-068: real agent-execution analytics -- success rate, duration percentiles, and daily run
 * volume, all computed from the real AgentRun ledger (src/agents/analytics.py), scoped to what
 * the existing Grafana dashboard doesn't already show (infra/WS/order latency). Deliberately
 * lives as a tab within the existing Agent Console rather than a new top-level nav entry -- this
 * is exactly where a user would already look for agent-execution insight. */
export function AgentAnalyticsPanel() {
  const [days, setDays] = useState<(typeof DAY_RANGES)[number]>(30);

  const summaryQuery = useQuery({
    queryKey: ["agent-analytics-summary", days],
    queryFn: () => api.agentAnalyticsSummary(days),
    refetchInterval: 30_000,
  });
  const trendQuery = useQuery({
    queryKey: ["agent-analytics-trend", days],
    queryFn: () => api.agentAnalyticsTrend(days),
    refetchInterval: 30_000,
  });

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[11px] text-text-faint">
          Real per-agent execution stats over the AgentRun ledger — every root graph run and
          every per-node child run.
        </p>
        <div
          className="inline-flex gap-0.5 rounded-lg border border-card-edge bg-bg p-0.5"
          role="group"
          aria-label="Day range"
        >
          {DAY_RANGES.map((range) => (
            <button
              key={range}
              type="button"
              onClick={() => setDays(range)}
              aria-pressed={days === range}
              className={cn(
                "rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors",
                days === range
                  ? "bg-panel text-text shadow-card"
                  : "text-text-faint hover:text-text-dim",
              )}
            >
              {range}d
            </button>
          ))}
        </div>
      </div>

      <Card eyebrow="Run Volume" title="Daily Runs (Completed vs. Failed)">
        {trendQuery.isLoading ? (
          <div className="h-[180px] animate-pulse rounded-xl bg-bg" />
        ) : (
          <AgentRunVolumeChart points={trendQuery.data ?? []} />
        )}
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card eyebrow="Ranked" title="Success Rate by Agent">
          {summaryQuery.isLoading ? (
            <div className="h-[220px] animate-pulse rounded-xl bg-bg" />
          ) : (
            <AgentSuccessRateChart rows={summaryQuery.data ?? []} />
          )}
        </Card>

        <Card eyebrow="Detail" title="Per-Agent Stats">
          {summaryQuery.isLoading ? (
            <div className="h-[220px] animate-pulse rounded-xl bg-bg" />
          ) : (
            <AgentSuccessRateTable rows={summaryQuery.data ?? []} />
          )}
        </Card>
      </div>
    </div>
  );
}
