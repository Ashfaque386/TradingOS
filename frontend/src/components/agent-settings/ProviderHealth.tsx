"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

/** FR-110 (constitution VI): real signals only. `p50_latency_ms` / `last_failure_at` are null
 * until the router grows persistent telemetry — shown as "—", never a fabricated number. */
export function ProviderHealth() {
  const { data, isLoading } = useQuery({
    queryKey: ["llm-provider-health"],
    queryFn: api.llmProviderHealth,
    refetchInterval: 15_000,
  });
  return (
    <Card eyebrow="Providers" title="Health" density="dense">
      {isLoading ? (
        <div className="h-10 animate-pulse rounded bg-bg" />
      ) : (
        <ul className="flex flex-col gap-1 text-xs">
          {(data ?? []).map((h) => (
            <li key={h.provider} className="flex items-center gap-2">
              <Badge variant={h.availability === "connected" ? "secondary" : "outline"}>
                {h.availability}
              </Badge>
              <span className="font-medium">{h.provider}</span>
              <span className="ml-auto text-text-faint">
                p50 {h.p50_latency_ms ?? "—"} · last fail {h.last_failure_at ?? "—"}
                {h.in_fallback ? " · in fallback" : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
