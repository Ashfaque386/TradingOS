"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { RequireAuth } from "@/lib/auth";
import { TopBar } from "@/components/layout/top-bar";
import { GlassCard } from "@/components/ui/glass-card";
import { ShadowModePanel } from "@/components/paper-trading/shadow-mode-panel";
import { PaperPositionsTable } from "@/components/paper-trading/paper-positions-table";
import { PaperTradesTable } from "@/components/paper-trading/paper-trades-table";

/**
 * REL-013: the Paper Trading Desk -- the dashboard the backend has had real, tested APIs for
 * since Phase 4 Epic E4.4 but no frontend page ever consumed (src/api/routers/paper_trading.py,
 * src/api/routers/shadow_mode.py). Every fill here is a simulated depth-walked broker quote,
 * never a real order -- this is the mandatory precursor to Live deployment (see the Go-Live
 * Readiness Gate on each strategy's review panel), independent of whether the connected broker
 * itself offers any paper-trading feature (neither Zerodha nor Upstox does).
 */
function PaperTradingDeskView() {
  const positionsQuery = useQuery({
    queryKey: ["paper-positions"],
    queryFn: () => api.paperPositions(),
    refetchInterval: 15_000,
  });
  const tradesQuery = useQuery({
    queryKey: ["paper-trades"],
    queryFn: () => api.paperTrades(),
    refetchInterval: 15_000,
  });
  const shadowQuery = useQuery({
    queryKey: ["shadow-mode-status"],
    queryFn: () => api.shadowModeStatus(),
    refetchInterval: 30_000,
  });

  return (
    <main className="mx-auto flex w-full max-w-[1440px] flex-1 flex-col gap-4 p-6 sm:p-8">
      <GlassCard eyebrow="Rule 3 · Go-Live Precursor" title="Shadow Mode — Broker Validation Streak">
        <ShadowModePanel status={shadowQuery.data} />
      </GlassCard>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <GlassCard eyebrow="Simulated Ledger" title="Paper Positions">
          {positionsQuery.isLoading ? (
            <div className="h-40 animate-pulse rounded-xl bg-white/5" />
          ) : (
            <PaperPositionsTable positions={positionsQuery.data ?? []} />
          )}
        </GlassCard>

        <GlassCard eyebrow="Simulated Ledger" title="Recent Paper Fills">
          {tradesQuery.isLoading ? (
            <div className="h-40 animate-pulse rounded-xl bg-white/5" />
          ) : (
            <PaperTradesTable trades={tradesQuery.data ?? []} />
          )}
        </GlassCard>
      </div>

      <GlassCard eyebrow="How this works" title="No broker paper-trading dependency">
        <p className="text-[11px] leading-relaxed text-zinc-500">
          Neither Zerodha nor Upstox provides a native paper-trading mode, so this desk never
          relies on one. Every fill above is computed locally: a real live Level-2 depth quote is
          fetched from whichever broker is configured, walked by a real slippage model to produce
          a realistic fill price and partial-fill probability, and written to a local ledger —{" "}
          <code className="text-zinc-400">place_order</code> is never called. Shadow Mode above
          is a separate, complementary check: it validates that a real order payload is
          syntactically correct against each broker&apos;s real API shape (a genuine sandbox call for
          Upstox, local-only validation for Zerodha, which has no sandbox at all) without ever
          risking capital either.
        </p>
      </GlassCard>
    </main>
  );
}

export default function PaperTradingPage() {
  return (
    <RequireAuth>
      <TopBar connected={false} subtitle="Paper Trading Desk — Simulated Fills, Zero Real Capital" />
      <PaperTradingDeskView />
    </RequireAuth>
  );
}
