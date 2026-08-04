"use client";

import { formatCompactINR } from "@/lib/utils";
import type { Margin } from "@/lib/api";

export function MarginPanel({ margin }: { margin: Margin | undefined }) {
  if (!margin) {
    return <div className="h-16 animate-pulse rounded-lg bg-bg" />;
  }

  const total = margin.available_margin + margin.used_margin;
  const usedPct = total > 0 ? (margin.used_margin / total) * 100 : 0;

  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="text-xs text-text-faint">Used</span>
        <span className="font-mono-tabular text-sm text-text">
          {formatCompactINR(margin.used_margin)}
        </span>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-bg">
        <div
          className="bg-brand-gradient h-full rounded-full transition-all duration-700"
          style={{ width: `${Math.min(usedPct, 100)}%` }}
        />
      </div>
      <div className="mt-2 flex items-baseline justify-between">
        <span className="text-xs text-text-faint">Available</span>
        <span className="font-mono-tabular text-sm text-text">
          {formatCompactINR(margin.available_margin)}
        </span>
      </div>
    </div>
  );
}
