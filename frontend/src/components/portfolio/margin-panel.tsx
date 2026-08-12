"use client";

import { formatCompactINR } from "@/lib/utils";
import type { Margin } from "@/lib/api";
import type { BrokerConnectionState } from "@/components/portfolio/broker-connection-banner";

/** REL-036: `state` distinguishes "still loading" (no `margin` yet, but the broker is fine) from
 * "not connected"/"connected but errored" -- previously this only ever showed a loading pulse
 * for any undefined `margin`, indistinguishable from a real connection problem. */
export function MarginPanel({
  margin,
  state = "ok",
}: {
  margin: Margin | undefined;
  state?: BrokerConnectionState;
}) {
  if (state !== "ok") {
    return (
      <div className="flex h-16 items-center justify-center rounded-lg bg-bg">
        <p className="text-[11px] text-text-faint">
          {state === "not_configured" ? "Not connected" : "Unreachable"}
        </p>
      </div>
    );
  }

  if (!margin) {
    return <div className="h-16 animate-pulse rounded-lg bg-bg" />;
  }

  const total = margin.available_margin + margin.used_margin;
  const usedPct = total > 0 ? (margin.used_margin / total) * 100 : 0;

  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="text-xs text-text-faint">Total Amount</span>
        <span className="font-mono-tabular text-sm font-semibold text-text">
          {formatCompactINR(total)}
        </span>
      </div>
      <div className="mt-1.5 flex items-baseline justify-between">
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
        <span className="text-xs text-text-faint">Available to Trade</span>
        <span className="font-mono-tabular text-sm font-semibold text-up">
          {formatCompactINR(margin.available_margin)}
        </span>
      </div>
    </div>
  );
}
