"use client";

import { formatCompactINR } from "@/lib/utils";
import type { Margin } from "@/lib/api";

export function MarginPanel({ margin }: { margin: Margin | undefined }) {
  if (!margin) {
    return <div className="h-16 animate-pulse rounded-lg bg-white/5" />;
  }

  const total = margin.available_margin + margin.used_margin;
  const usedPct = total > 0 ? (margin.used_margin / total) * 100 : 0;

  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="text-xs text-zinc-500">Used</span>
        <span className="font-mono-tabular text-sm text-zinc-200">
          {formatCompactINR(margin.used_margin)}
        </span>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-white/5">
        <div
          className="h-full rounded-full bg-gradient-to-r from-cyan-400 to-purple-400 transition-all duration-700"
          style={{ width: `${Math.min(usedPct, 100)}%` }}
        />
      </div>
      <div className="mt-2 flex items-baseline justify-between">
        <span className="text-xs text-zinc-500">Available</span>
        <span className="font-mono-tabular text-sm text-zinc-200">
          {formatCompactINR(margin.available_margin)}
        </span>
      </div>
    </div>
  );
}
