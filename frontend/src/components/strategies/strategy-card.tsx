"use client";

import { motion, type PanInfo } from "framer-motion";
import { useRef } from "react";
import { cn } from "@/lib/utils";
import type { StrategySummary } from "@/lib/api";

const VALIDATION_COLOR: Record<string, string> = {
  Passed: "text-up",
  Failed: "text-down",
  Pending: "text-warn",
};

export function StrategyCard({
  strategy,
  selected,
  onSelect,
  onDragEnd,
  draggable,
}: {
  strategy: StrategySummary;
  selected: boolean;
  onSelect: () => void;
  onDragEnd: (info: PanInfo) => void;
  /** REL-011 E11.3: gates only the drag-to-promote interaction (usePermission("promoteStrategy")
   * in the parent board) -- the card itself stays visible/readable for every role, since the
   * board is a legitimate read surface and only the mutating drag gesture needs gating. */
  draggable: boolean;
}) {
  const dragging = useRef(false);

  return (
    <motion.div
      drag={draggable}
      dragSnapToOrigin
      dragElastic={0.15}
      whileDrag={draggable ? { scale: 1.04, zIndex: 20, boxShadow: "0 20px 40px rgba(0,0,0,0.5)" } : undefined}
      onDragStart={() => {
        dragging.current = true;
      }}
      onDragEnd={(_e, info) => {
        onDragEnd(info);
        setTimeout(() => {
          dragging.current = false;
        }, 0);
      }}
      onClick={() => {
        if (!dragging.current) onSelect();
      }}
      className={cn(
        "select-none rounded-xl border p-3 transition-colors",
        draggable && "cursor-grab active:cursor-grabbing",
        selected
          ? "border-brand-via/40 bg-brand-via/[0.06]"
          : "border-card-edge bg-panel hover:border-text-faint",
      )}
    >
      <p className="line-clamp-2 text-xs font-medium text-text">{strategy.name}</p>
      <div className="mt-2 flex items-center justify-between text-[10px] text-text-faint">
        <span>
          {strategy.asset_class} · {strategy.style}
        </span>
        {strategy.universe && strategy.universe.length > 0 && (
          <span className="font-mono-tabular text-text-dim">{strategy.universe[0]}</span>
        )}
      </div>
    </motion.div>
  );
}

export { VALIDATION_COLOR };
