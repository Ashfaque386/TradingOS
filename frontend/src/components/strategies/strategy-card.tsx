"use client";

import { BarChart3 } from "lucide-react";
import { motion, type PanInfo } from "framer-motion";
import { useRef } from "react";
import { cn } from "@/lib/utils";
import { staggerItem } from "@/lib/motion";
import type { StrategySummary } from "@/lib/api";

const VALIDATION_COLOR: Record<string, string> = {
  Passed: "text-up",
  Failed: "text-down",
  Pending: "text-warn",
};

const VALIDATION_DOT_COLOR: Record<string, string> = {
  Passed: "bg-up",
  Failed: "bg-down",
  Pending: "bg-warn",
};

const ASSET_CLASS_TAG: Record<string, string> = {
  "F&O": "border-brand-via/30 bg-brand-via/[0.08] text-brand-via",
  Equity: "border-card-edge bg-bg text-text-dim",
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
      variants={staggerItem}
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
        "select-none rounded-xl border p-3 transition-all",
        draggable && "cursor-grab active:cursor-grabbing",
        selected
          ? "border-brand-via/40 bg-brand-via/[0.06] shadow-card"
          : "border-card-edge bg-panel hover:border-text-faint hover:shadow-card",
      )}
    >
      <div className="flex items-start justify-between gap-1.5">
        <p className="line-clamp-2 text-xs font-medium leading-snug text-text">{strategy.name}</p>
        {strategy.current_version_validation_status && (
          <span
            className={cn(
              "mt-0.5 h-1.5 w-1.5 flex-shrink-0 rounded-full",
              VALIDATION_DOT_COLOR[strategy.current_version_validation_status] ?? "bg-text-faint",
            )}
            title={`Current version: ${strategy.current_version_validation_status}`}
          />
        )}
      </div>
      {strategy.hypothesis && (
        <p className="mt-1.5 line-clamp-2 text-[10px] leading-relaxed text-text-faint">
          {strategy.hypothesis}
        </p>
      )}
      <div className="mt-2.5 flex flex-wrap items-center gap-1">
        <span
          className={cn(
            "rounded-full border px-1.5 py-0.5 text-[9px] font-medium",
            ASSET_CLASS_TAG[strategy.asset_class] ?? "border-card-edge bg-bg text-text-dim",
          )}
        >
          {strategy.asset_class}
        </span>
        <span className="rounded-full border border-card-edge bg-bg px-1.5 py-0.5 text-[9px] text-text-faint">
          {strategy.style}
        </span>
        {strategy.universe && strategy.universe.length > 0 && (
          <span className="font-mono-tabular ml-auto text-[9px] text-text-dim">
            {strategy.universe[0]}
          </span>
        )}
      </div>
      {strategy.backtest_count > 0 && (
        <div className="mt-1.5 flex items-center gap-1 text-[9px] text-text-faint">
          <BarChart3 className="h-2.5 w-2.5" />
          <span className="font-mono-tabular">
            {strategy.backtest_count} {strategy.backtest_count === 1 ? "backtest" : "backtests"}
          </span>
        </div>
      )}
    </motion.div>
  );
}

export { VALIDATION_COLOR };
