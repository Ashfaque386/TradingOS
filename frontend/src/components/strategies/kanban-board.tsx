"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { PanInfo } from "framer-motion";
import { useRef } from "react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { usePermission } from "@/lib/usePermission";
import type { StrategyStatus, StrategySummary } from "@/lib/api";
import { StrategyCard } from "./strategy-card";

const COLUMNS: { status: StrategyStatus; label: string; promotable: boolean }[] = [
  { status: "Ideation", label: "Ideation", promotable: false },
  { status: "Coding", label: "Coding", promotable: false },
  { status: "Backtesting", label: "Backtesting", promotable: true },
  { status: "PaperTrading", label: "Paper Trading", promotable: true },
  { status: "Live", label: "Live", promotable: true },
];

export function KanbanBoard({
  strategies,
  selectedId,
  onSelect,
}: {
  strategies: StrategySummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const queryClient = useQueryClient();
  const columnRefs = useRef<Partial<Record<StrategyStatus, HTMLDivElement | null>>>({});
  // REL-011 E11.3: this drag-to-promote gesture is a real mutating control (POST
  // /strategies/{id}/promote, server-gated SA/PM) that previously had NO client-side role
  // check at all -- any role could drag a card and attempt a promote (it would 403 server-side,
  // but the UI let them try). The board itself stays visible/readable for every role; only the
  // drag interaction is gated.
  const canPromote = usePermission("promoteStrategy");

  const promote = useMutation({
    mutationFn: ({ id, toStatus }: { id: string; toStatus: StrategyStatus }) =>
      api.promoteStrategy(id, toStatus),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["strategies"] }),
  });

  const byStatus = (status: StrategyStatus) => strategies.filter((s) => s.status === status);

  const handleDragEnd = (strategy: StrategySummary, info: PanInfo) => {
    if (!canPromote) return;
    const point = { x: info.point.x, y: info.point.y };
    for (const col of COLUMNS) {
      const el = columnRefs.current[col.status];
      if (!el) continue;
      const rect = el.getBoundingClientRect();
      const inside =
        point.x >= rect.left && point.x <= rect.right && point.y >= rect.top && point.y <= rect.bottom;
      if (inside && col.status !== strategy.status) {
        if (!col.promotable) return; // dropping onto an agent-only column is a no-op, snaps back
        promote.mutate({ id: strategy.id, toStatus: col.status });
        return;
      }
    }
  };

  return (
    <div>
      {!canPromote && (
        <p
          data-testid="kanban-readonly-banner"
          className="mb-3 text-[11px] text-zinc-500"
        >
          Your role can view strategy status but cannot drag a card to promote it. Requires
          System Administrator or Portfolio Manager.
        </p>
      )}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5">
      {COLUMNS.map((col) => {
        const items = byStatus(col.status);
        return (
          <div
            key={col.status}
            ref={(el) => {
              columnRefs.current[col.status] = el;
            }}
            className={cn(
              "flex min-h-[200px] flex-col gap-2 rounded-2xl border border-white/5 bg-black/20 p-3",
              !col.promotable && "border-dashed",
            )}
          >
            <div className="mb-1 flex items-center justify-between px-0.5">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-400">
                {col.label}
              </span>
              <span className="rounded-full bg-white/5 px-1.5 py-0.5 text-[10px] text-zinc-500">
                {items.length}
              </span>
            </div>
            {items.length === 0 && (
              <div className="flex flex-1 items-center justify-center py-6 text-center text-[10px] text-zinc-600">
                Empty
              </div>
            )}
            {items.map((s) => (
              <StrategyCard
                key={s.id}
                strategy={s}
                selected={s.id === selectedId}
                onSelect={() => onSelect(s.id)}
                onDragEnd={(info) => handleDragEnd(s, info)}
                draggable={canPromote}
              />
            ))}
          </div>
        );
      })}
      </div>
    </div>
  );
}
