"use client";

import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, CircleDashed, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { GlassCard } from "@/components/ui/glass-card";

/**
 * REL-013: surfaces src/engine/go_live_gate.py's authoritative 4-condition Go-Live Readiness
 * Gate (Phase_14_Master_Development_Roadmap.md §5.4) -- the real replacement for the earlier
 * fixed "2 weeks" / "2 months" paper-trading duration figures. A strategy only clears this once
 * it has accumulated enough real paper-traded (never real-money) trades across enough calendar
 * time, with a clean Shadow Mode broker-validation streak, and live performance that hasn't
 * diverged from its own backtest. Previously computed by the backend with zero frontend view.
 */
export function GoLiveGatePanel({ strategyId }: { strategyId: string }) {
  const query = useQuery({
    queryKey: ["go-live-readiness", strategyId],
    queryFn: () => api.goLiveReadiness(strategyId),
  });

  return (
    <GlassCard
      eyebrow="Rule 3 · Human-in-the-Loop"
      title="Go-Live Readiness Gate"
      action={
        query.data && (
          <span
            className={cn(
              "flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider",
              query.data.gate_met
                ? "bg-emerald-400/10 text-emerald-300"
                : "bg-white/5 text-zinc-500",
            )}
          >
            <ShieldCheck className="h-3 w-3" />
            {query.data.gate_met ? "Gate met" : "Not cleared"}
          </span>
        )
      }
    >
      <p className="mb-3 text-[11px] leading-relaxed text-zinc-500">
        All four conditions below must independently hold before this strategy can be recommended
        for Live deployment — every trade counted here is a simulated paper fill against real
        broker quotes, never real capital.
      </p>

      {!query.data ? (
        <div className="h-28 animate-pulse rounded-xl bg-white/5" />
      ) : (
        <ul className="flex flex-col gap-2">
          {query.data.conditions.map((c) => (
            <li
              key={c.label}
              className="flex items-start gap-2.5 rounded-lg bg-white/[0.03] p-2.5"
            >
              {c.met ? (
                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-emerald-400" />
              ) : (
                <CircleDashed className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-zinc-600" />
              )}
              <div>
                <div
                  className={cn(
                    "text-xs font-medium",
                    c.met ? "text-zinc-200" : "text-zinc-400",
                  )}
                >
                  {c.label}
                </div>
                <div className="text-[11px] text-zinc-500">{c.detail}</div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </GlassCard>
  );
}
