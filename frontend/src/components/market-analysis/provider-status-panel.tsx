"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/card";

const PROVIDER_LABELS: Record<string, string> = {
  upstox_v3: "Upstox V3",
  yfinance: "Yahoo Finance",
};

/** REL-073 (Phase 4 of the Upstox V3 + yfinance dual market-data system): real provider
 * configuration status, via GET /market/providers/status -- a config-only check (no live
 * network call, matching src/api/routers/broker_config.py's own broker_status() shape), never
 * exposing a token value. `active_provider` reflects the real configured
 * primary/fallback resolution build_market_data_manager() (src/data/providers/manager.py)
 * performs at ingestion time. */
export function ProviderStatusPanel() {
  const statusQuery = useQuery({
    queryKey: ["provider-status"],
    queryFn: api.providerStatus,
    refetchInterval: 5 * 60_000,
  });

  const status = statusQuery.data;

  return (
    <Card eyebrow="Market Data Providers" title="Provider Status" density="dense">
      {statusQuery.isLoading ? (
        <div className="h-10 animate-pulse rounded-xl bg-bg" />
      ) : !status ? (
        <p className="text-xs text-text-faint">Could not reach the provider status check.</p>
      ) : (
        <div className="flex flex-col gap-2">
          {status.providers.map((provider) => (
            <div key={provider.name} className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <span
                  className={cn(
                    "h-2 w-2 rounded-full",
                    provider.configured ? "bg-up" : "bg-down",
                  )}
                />
                <span className="text-sm font-medium text-text">
                  {PROVIDER_LABELS[provider.name] ?? provider.name}
                </span>
                {provider.name === status.active_provider && (
                  <span className="rounded-full bg-brand-via/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-brand-via">
                    Active
                  </span>
                )}
              </div>
              <span
                className={cn(
                  "text-xs font-medium",
                  provider.configured ? "text-up" : "text-text-faint",
                )}
              >
                {provider.configured ? "Configured" : (provider.detail ?? "Not configured")}
              </span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
