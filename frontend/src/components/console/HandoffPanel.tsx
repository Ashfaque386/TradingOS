"use client";

import { useQuery } from "@tanstack/react-query";
import { api, type OrgHandoff } from "@/lib/api";
import { parseBackendTimestamp } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const NONE = "text-[11px] italic text-text-faint";

/** spec 002 US3: agent-to-agent handoffs as a first-class, inspectable list -- sender,
 * receiver, artefact, timestamp, and what was expected but missing -- not a meaningless arrow
 * inferred from task order. `agentName` scopes the view to one agent's inbound/outbound
 * handoffs (used inside AgentDetail, US4); omit it for the full per-run handoff chain. */
export function HandoffPanel({ runId, agentName }: { runId: string; agentName?: string }) {
  const handoffsQuery = useQuery({
    queryKey: ["org-handoffs", runId],
    queryFn: () => api.orgHandoffs(runId),
    refetchInterval: 6_000,
  });

  const all = handoffsQuery.data ?? [];
  const inbound = agentName ? all.filter((h) => h.to_agent === agentName) : [];
  const outbound = agentName ? all.filter((h) => h.from_agent === agentName) : [];

  if (handoffsQuery.isLoading) return <div className="h-16 animate-pulse rounded-card bg-bg" />;

  if (agentName) {
    return (
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <HandoffList title="Received from" rows={inbound} showSide="from" />
        <HandoffList title="Delivered to" rows={outbound} showSide="to" />
      </div>
    );
  }

  return <HandoffList title="Handoffs" rows={all} showSide="both" />;
}

function HandoffList({
  title,
  rows,
  showSide,
}: {
  title: string;
  rows: OrgHandoff[];
  showSide: "from" | "to" | "both";
}) {
  return (
    <Card eyebrow="Handoff" title={title} density="dense">
      {rows.length === 0 ? (
        <p className={NONE}>No handoffs recorded yet.</p>
      ) : (
        <ul className="flex flex-col gap-2 text-xs">
          {rows.map((h) => (
            <li
              key={`${h.artefact_id}-${h.to_task_id}`}
              className="rounded-lg border border-card-edge p-2"
            >
              <div className="flex items-center gap-1.5">
                {showSide !== "to" && <span className="font-medium">{h.from_agent ?? "—"}</span>}
                {showSide === "both" && <span className="text-text-faint">→</span>}
                {showSide !== "from" && <span className="font-medium">{h.to_agent ?? "—"}</span>}
                <Badge variant="outline" className="ml-auto">
                  {h.artefact_type}
                </Badge>
              </div>
              <div className="mt-1 flex items-center justify-between text-text-faint">
                <span>{parseBackendTimestamp(h.delivered_at).toLocaleString()}</span>
                {h.requested_but_missing.length > 0 && (
                  <span className="text-destructive">
                    missing: {h.requested_but_missing.join(", ")}
                  </span>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
