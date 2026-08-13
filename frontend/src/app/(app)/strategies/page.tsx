"use client";

import { useQuery } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { useMemo, useState } from "react";
import { api } from "@/lib/api";
import { usePageStatus } from "@/hooks/usePageStatus";
import { Card } from "@/components/ui/card";
import { IconBadge } from "@/components/ui/icon-badge";
import { KanbanBoard } from "@/components/strategies/kanban-board";
import { ReviewPanel } from "@/components/strategies/review-panel";
import type { StrategySummary } from "@/lib/api";
import {
  DEFAULT_STRATEGY_FILTER_STATE,
  StrategyFilterBar,
  type StrategyFilterState,
} from "@/components/strategies/strategy-filter-bar";

const EMPTY_STRATEGIES: StrategySummary[] = [];

export default function StrategiesPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filter, setFilter] = useState<StrategyFilterState>(DEFAULT_STRATEGY_FILTER_STATE);

  const strategiesQuery = useQuery({
    queryKey: ["strategies"],
    queryFn: api.strategies,
    refetchInterval: 5_000,
  });

  usePageStatus("Strategy Deployment & Backtest Review", strategiesQuery.isSuccess);

  const strategies = strategiesQuery.data ?? EMPTY_STRATEGIES;

  const filteredStrategies = useMemo(() => {
    const search = filter.search.trim().toLowerCase();
    return strategies.filter((s) => {
      if (filter.assetClass !== "All" && s.asset_class !== filter.assetClass) return false;
      if (filter.style !== "All" && s.style !== filter.style) return false;
      if (!filter.stages.has(s.status)) return false;
      if (search) {
        const haystack = `${s.name} ${s.hypothesis ?? ""}`.toLowerCase();
        if (!haystack.includes(search)) return false;
      }
      return true;
    });
  }, [strategies, filter]);

  const effectiveSelectedId =
    selectedId ?? filteredStrategies[0]?.id ?? strategies[0]?.id ?? null;

  return (
    <main className="mx-auto flex w-full max-w-[1440px] flex-1 flex-col gap-4 p-6 sm:p-8">
      <Card eyebrow="Pipeline" title="Strategy Kanban">
        {strategies.length === 0 && !strategiesQuery.isLoading ? (
          <div className="flex h-32 flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-card-edge text-center">
            <IconBadge floating size={36}>
              <Sparkles className="h-4 w-4 text-text-faint" />
            </IconBadge>
            <p className="text-xs text-text-faint">
              No strategies yet — trigger a research cycle from the Agent Console to generate
              one.
            </p>
          </div>
        ) : (
          <>
            <StrategyFilterBar value={filter} onChange={setFilter} />
            {filteredStrategies.length === 0 ? (
              <div className="flex h-24 flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-card-edge text-center">
                <p className="text-xs text-text-faint">
                  No strategies match the current filters.
                </p>
              </div>
            ) : (
              <KanbanBoard
                strategies={filteredStrategies}
                selectedId={effectiveSelectedId}
                onSelect={setSelectedId}
                visibleStages={filter.stages}
              />
            )}
          </>
        )}
      </Card>

      {effectiveSelectedId && <ReviewPanel strategyId={effectiveSelectedId} />}
    </main>
  );
}
