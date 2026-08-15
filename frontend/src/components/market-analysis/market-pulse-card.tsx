"use client";

import { useQuery } from "@tanstack/react-query";
import { TrendingDown, TrendingUp } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { NumberTicker } from "@/components/ui/number-ticker";

/** REL-067: real India VIX level + day change, via GET /market/pulse -- the same real yfinance
 * data the Market Analyst Agent's own IndiaVixSkill already fetches. VIX is a fear gauge, so its
 * color semantics are inverted from every other up/down figure in this app: a rising VIX is bad
 * news (colored `text-down`), a falling VIX is calm (colored `text-up`) -- flagged explicitly
 * here since it's the one place in the app where "up" isn't good. */
export function MarketPulseCard() {
  const pulseQuery = useQuery({
    queryKey: ["market-pulse"],
    queryFn: api.marketPulse,
    refetchInterval: 60_000,
  });

  const vix = pulseQuery.data?.india_vix;
  const rising = (vix?.change_pct ?? 0) > 0;

  return (
    <Card eyebrow="Fear Gauge" title="India VIX">
      {pulseQuery.isLoading ? (
        <div className="h-16 animate-pulse rounded-xl bg-bg" />
      ) : !vix ? (
        <p className="text-xs text-text-faint">
          No real India VIX data available right now — Yahoo Finance returned nothing for
          ^INDIAVIX on the last request.
        </p>
      ) : (
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <NumberTicker
              value={vix.value}
              format={(v) => v.toFixed(2)}
              className="font-mono-tabular text-4xl font-semibold tracking-tight text-text"
            />
            <p className="mt-1 text-[11px] text-text-faint">As of {vix.as_of}</p>
          </div>
          <div
            className={cn(
              "flex items-center gap-1 rounded-full px-3 py-1.5 text-sm font-semibold",
              rising ? "bg-down/10 text-down" : "bg-up/10 text-up",
            )}
          >
            {rising ? <TrendingUp className="h-4 w-4" /> : <TrendingDown className="h-4 w-4" />}
            {rising ? "+" : ""}
            {vix.change_pct.toFixed(2)}%
          </div>
        </div>
      )}
    </Card>
  );
}
