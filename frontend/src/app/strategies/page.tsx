"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { RequireAuth } from "@/lib/auth";
import { TopBar } from "@/components/layout/top-bar";
import { GlassCard } from "@/components/ui/glass-card";
import { KanbanBoard } from "@/components/strategies/kanban-board";
import { ReviewPanel } from "@/components/strategies/review-panel";

export default function StrategiesPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const strategiesQuery = useQuery({
    queryKey: ["strategies"],
    queryFn: api.strategies,
    refetchInterval: 5_000,
  });

  const strategies = strategiesQuery.data ?? [];
  const effectiveSelectedId = selectedId ?? strategies[0]?.id ?? null;

  return (
    <RequireAuth>
      <TopBar connected={strategiesQuery.isSuccess} subtitle="Strategy Deployment & Backtest Review" />

      <main className="mx-auto flex w-full max-w-[1440px] flex-1 flex-col gap-4 p-6 sm:p-8">
        <GlassCard eyebrow="Pipeline" title="Strategy Kanban">
          {strategies.length === 0 && !strategiesQuery.isLoading ? (
            <div className="flex h-32 flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-white/10 text-center">
              <p className="text-xs text-zinc-500">
                No strategies yet — trigger a research cycle from the Agent Console to generate
                one.
              </p>
            </div>
          ) : (
            <KanbanBoard
              strategies={strategies}
              selectedId={effectiveSelectedId}
              onSelect={setSelectedId}
            />
          )}
        </GlassCard>

        {effectiveSelectedId && <ReviewPanel strategyId={effectiveSelectedId} />}
      </main>
    </RequireAuth>
  );
}
