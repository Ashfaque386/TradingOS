"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, Ban, CircleCheck, Info, ShieldAlert } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Gated } from "@/components/ui/gated";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { slideUp } from "@/lib/motion";
import type { AgentControlEntry } from "@/lib/api";

const KIND_LABEL: Record<AgentControlEntry["kind"], string> = {
  graph_node: "Pipeline node",
  scheduled: "Scheduled job",
  registry_only: "Registry only",
};

type SortKey = "agent" | "kind" | "status";

function sortValue(entry: AgentControlEntry, key: SortKey): string {
  if (key === "agent") return entry.display_name.toLowerCase();
  if (key === "kind") return KIND_LABEL[entry.kind];
  return entry.enabled ? "0-enabled" : "1-disabled";
}

function SortableHead({
  sortKey,
  sort,
  onToggle,
  children,
}: {
  sortKey: SortKey;
  sort: { key: SortKey; dir: "asc" | "desc" };
  onToggle: (key: SortKey) => void;
  children: React.ReactNode;
}) {
  const active = sort.key === sortKey;
  return (
    <TableHead className="h-auto px-0 pb-2">
      <button
        onClick={() => onToggle(sortKey)}
        className="flex items-center gap-1 text-[10px] font-medium uppercase tracking-wider text-text-faint transition hover:text-text-dim"
      >
        {children}
        {active &&
          (sort.dir === "asc" ? (
            <ArrowUp className="h-2.5 w-2.5" />
          ) : (
            <ArrowDown className="h-2.5 w-2.5" />
          ))}
      </button>
    </TableHead>
  );
}

/** REL-019 E19.2/E19.3 (ADR 11): per-agent registry replacing the Agent Console's previous
 * "one shared run-level status" view. `enforced` (src/agents/control.py::KNOWN_AGENTS) is shown
 * honestly per-agent -- a `registry_only` row's toggle still writes real, durable state, it just
 * doesn't stop anything yet, and the UI says so rather than implying uniform enforcement.
 *
 * Phase 2B: promoted from a card-list to a real sortable table + a detail drawer per row, since
 * `AgentControlEntry` already carries `updated_by`/`updated_at` that the old card view never
 * surfaced at all. */
export function AgentRegistry() {
  const queryClient = useQueryClient();
  const [pendingDisable, setPendingDisable] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [detailAgent, setDetailAgent] = useState<AgentControlEntry | null>(null);
  const [sort, setSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({
    key: "agent",
    dir: "asc",
  });

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

  const sortedEntries = useMemo(() => {
    const entries = registryQuery.data ?? [];
    const dirMul = sort.dir === "asc" ? 1 : -1;
    return [...entries].sort(
      (a, b) => sortValue(a, sort.key).localeCompare(sortValue(b, sort.key)) * dirMul,
    );
  }, [registryQuery.data, sort]);

  function toggleSort(key: SortKey) {
    setSort((prev) =>
      prev.key === key ? { key, dir: prev.dir === "asc" ? "desc" : "asc" } : { key, dir: "asc" },
    );
  }

  if (registryQuery.isLoading) {
    return <div className="h-40 animate-pulse rounded-xl bg-bg" />;
  }

  return (
    <>
      <div className="overflow-x-auto">
        <Table className="text-xs">
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <SortableHead sortKey="agent" sort={sort} onToggle={toggleSort}>
                Agent
              </SortableHead>
              <SortableHead sortKey="kind" sort={sort} onToggle={toggleSort}>
                Kind
              </SortableHead>
              <TableHead className="h-auto px-0 pb-2 text-[10px] font-medium uppercase tracking-wider text-text-faint">
                Enforcement
              </TableHead>
              <SortableHead sortKey="status" sort={sort} onToggle={toggleSort}>
                Status
              </SortableHead>
              <TableHead className="h-auto px-0 pb-2 text-right text-[10px] font-medium uppercase tracking-wider text-text-faint">
                Actions
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sortedEntries.map((agent) => {
              const isPendingThis =
                setEnabled.isPending && setEnabled.variables?.agentName === agent.agent_name;
              return (
                <TableRow key={agent.agent_name} className="border-card-edge align-top">
                  <TableCell className="px-0 py-row-dense">
                    <div className="flex flex-col gap-0.5">
                      <span className="text-[11px] font-medium text-text">{agent.display_name}</span>
                      <span className="font-mono-tabular text-[9px] text-text-faint">
                        {agent.agent_id}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell className="px-0 py-row-dense">
                    <Badge variant="secondary" className="font-normal">
                      {KIND_LABEL[agent.kind]}
                    </Badge>
                  </TableCell>
                  <TableCell className="px-0 py-row-dense">
                    {agent.enforced ? (
                      <Badge variant="outline" className="border-up/30 text-up">
                        <CircleCheck className="h-2.5 w-2.5" /> Enforced
                      </Badge>
                    ) : (
                      <Badge variant="outline" className="border-warn/30 text-warn">
                        <ShieldAlert className="h-2.5 w-2.5" /> Not yet enforced
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell className="px-0 py-row-dense">
                    <div className="flex flex-col gap-1">
                      <Badge
                        variant="outline"
                        className={cn(
                          "w-fit",
                          agent.enabled ? "border-up/30 text-up" : "border-down/30 text-down",
                        )}
                      >
                        {agent.enabled ? (
                          <CircleCheck className="h-2.5 w-2.5" />
                        ) : (
                          <Ban className="h-2.5 w-2.5" />
                        )}
                        {agent.enabled ? "Enabled" : "Disabled"}
                      </Badge>
                      {!agent.enabled && agent.reason && (
                        <span className="max-w-[200px] truncate text-[10px] text-text-faint">
                          {agent.reason}
                        </span>
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="px-0 py-row-dense">
                    <div className="flex items-center justify-end gap-1.5">
                      <button
                        onClick={() => setDetailAgent(agent)}
                        title="View details"
                        className="rounded-md p-1 text-text-faint transition hover:bg-bg hover:text-text-dim"
                      >
                        <Info className="h-3.5 w-3.5" />
                      </button>
                      <Gated permission="manageAgentControl" fallback={null}>
                        {agent.enabled ? (
                          <AnimatePresence initial={false}>
                            {pendingDisable === agent.agent_name ? (
                              <motion.div
                                key="disable-form"
                                initial="hidden"
                                animate="visible"
                                exit="exit"
                                variants={slideUp}
                                className="flex items-center gap-1.5"
                              >
                                <input
                                  value={reason}
                                  onChange={(e) => setReason(e.target.value)}
                                  placeholder="Reason"
                                  autoFocus
                                  className="w-28 rounded-md border border-card-edge bg-panel px-1.5 py-1 text-[10px] text-text placeholder:text-text-faint"
                                />
                                <Button
                                  onClick={() =>
                                    setEnabled.mutate({
                                      agentName: agent.agent_name,
                                      enabled: false,
                                      reason: reason || null,
                                    })
                                  }
                                  disabled={!reason.trim() || isPendingThis}
                                  variant="destructive"
                                  className="px-2 py-1 text-[10px]"
                                >
                                  Confirm
                                </Button>
                                <Button
                                  onClick={() => setPendingDisable(null)}
                                  variant="secondary"
                                  className="px-2 py-1 text-[10px]"
                                >
                                  Cancel
                                </Button>
                              </motion.div>
                            ) : (
                              <Button
                                key="disable-trigger"
                                onClick={() => {
                                  setPendingDisable(agent.agent_name);
                                  setReason("");
                                }}
                                variant="destructive"
                                className="shrink-0 px-2 py-1 text-[10px]"
                              >
                                <Ban className="h-3 w-3" /> Disable
                              </Button>
                            )}
                          </AnimatePresence>
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
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      <Sheet open={detailAgent !== null} onOpenChange={(open) => !open && setDetailAgent(null)}>
        <SheetContent>
          {detailAgent && (
            <>
              <SheetHeader>
                <SheetTitle>{detailAgent.display_name}</SheetTitle>
                <SheetDescription>{KIND_LABEL[detailAgent.kind]}</SheetDescription>
              </SheetHeader>
              <div className="flex flex-col gap-4 px-4 pb-4 text-xs">
                <DetailRow label="Agent ID" value={detailAgent.agent_id} mono />
                <DetailRow
                  label="Enforcement"
                  value={
                    detailAgent.enforced
                      ? "Enforced — disabling this agent stops it from running"
                      : "Not yet enforced — toggling writes durable state, but no call site checks it yet"
                  }
                />
                <DetailRow label="Status" value={detailAgent.enabled ? "Enabled" : "Disabled"} />
                {!detailAgent.enabled && detailAgent.reason && (
                  <DetailRow label="Disable reason" value={detailAgent.reason} />
                )}
                {detailAgent.updated_by && (
                  <DetailRow label="Last changed by" value={detailAgent.updated_by} />
                )}
                {detailAgent.updated_at && (
                  <DetailRow
                    label="Last changed at"
                    value={new Date(detailAgent.updated_at).toLocaleString("en-IN", {
                      timeZone: "Asia/Kolkata",
                    })}
                    mono
                  />
                )}
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </>
  );
}

function DetailRow({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[10px] uppercase tracking-wider text-text-faint">{label}</span>
      <span className={cn("text-text", mono && "font-mono-tabular text-[11px]")}>{value}</span>
    </div>
  );
}
