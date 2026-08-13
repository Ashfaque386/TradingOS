"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { motion, type PanInfo } from "framer-motion";
import { Code2, FlaskConical, Lightbulb, Radio, Wallet } from "lucide-react";
import { useRef } from "react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { usePermission } from "@/lib/usePermission";
import { staggerContainer } from "@/lib/motion";
import type { StrategyStatus, StrategySummary } from "@/lib/api";
import { StrategyCard } from "./strategy-card";

const COLUMNS: {
  status: StrategyStatus;
  label: string;
  promotable: boolean;
  icon: typeof Lightbulb;
}[] = [
  { status: "Ideation", label: "Ideation", promotable: false, icon: Lightbulb },
  { status: "Coding", label: "Coding", promotable: false, icon: Code2 },
  { status: "Backtesting", label: "Backtesting", promotable: true, icon: FlaskConical },
  { status: "PaperTrading", label: "Paper Trading", promotable: true, icon: Wallet },
  { status: "Live", label: "Live", promotable: true, icon: Radio },
];

export function KanbanBoard({
  strategies,
  selectedId,
  onSelect,
  visibleStages,
}: {
  strategies: StrategySummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  /** REL-047: columns whose status isn't in this set are hidden entirely (not just emptied) --
   * lets the Stage filter genuinely collapse the board (e.g. down to just "Backtesting") instead
   * of always reserving grid space for all 5 columns. Defaults to all columns visible so callers
   * that don't pass it (none left in this codebase, kept for safety) see today's behavior. */
  visibleStages?: Set<StrategyStatus>;
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
  const visibleColumns = COLUMNS.filter((col) => !visibleStages || visibleStages.has(col.status));
  const gridColsClass =
    visibleColumns.length >= 5
      ? "xl:grid-cols-5"
      : visibleColumns.length === 4
        ? "xl:grid-cols-4"
        : visibleColumns.length === 3
          ? "xl:grid-cols-3"
          : visibleColumns.length === 2
            ? "xl:grid-cols-2"
            : "xl:grid-cols-1";

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
          className="mb-3 text-[11px] text-text-faint"
        >
          Your role can view strategy status but cannot drag a card to promote it. Requires
          System Administrator or Portfolio Manager.
        </p>
      )}
      <div className={cn("grid grid-cols-1 gap-3 sm:grid-cols-2", gridColsClass)}>
      {visibleColumns.map((col) => {
        const items = byStatus(col.status);
        return (
          <motion.div
            key={col.status}
            ref={(el) => {
              columnRefs.current[col.status] = el;
            }}
            initial="hidden"
            animate="visible"
            variants={staggerContainer}
            className={cn(
              "flex max-h-[calc(100vh-320px)] min-h-[200px] flex-col gap-2 rounded-2xl border border-card-edge bg-bg p-3",
              !col.promotable && "border-dashed",
            )}
          >
            <div className="mb-1 flex flex-shrink-0 items-center justify-between px-0.5">
              <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-text-dim">
                <col.icon className="h-3 w-3" />
                {col.label}
              </span>
              <span className="rounded-full bg-panel px-1.5 py-0.5 text-[10px] text-text-faint">
                {items.length}
              </span>
            </div>
            <div className="flex flex-1 flex-col gap-2 overflow-y-auto pr-0.5">
            {items.length === 0 && (
              <div className="flex flex-1 items-center justify-center py-6 text-center text-[10px] text-text-faint">
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
          </motion.div>
        );
      })}
      </div>
    </div>
  );
}
