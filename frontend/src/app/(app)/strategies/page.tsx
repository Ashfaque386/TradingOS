"use client";

import { useQuery } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { usePageStatus } from "@/hooks/usePageStatus";
import { Card } from "@/components/ui/card";
import { IconBadge } from "@/components/ui/icon-badge";
import { KanbanBoard } from "@/components/strategies/kanban-board";
import { ReviewPanel } from "@/components/strategies/review-panel";

export default function StrategiesPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const strategiesQuery = useQuery({
    queryKey: ["strategies"],
    queryFn: api.strategies,
    refetchInterval: 5_000,
  });

  usePageStatus("Strategy Deployment & Backtest Review", strategiesQuery.isSuccess);

  const strategies = strategiesQuery.data ?? [];
  const effectiveSelectedId = selectedId ?? strategies[0]?.id ?? null;

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
          <KanbanBoard
            strategies={strategies}
            selectedId={effectiveSelectedId}
            onSelect={setSelectedId}
          />
        )}
      </Card>

      {effectiveSelectedId && <ReviewPanel strategyId={effectiveSelectedId} />}
    </main>
  );
}
