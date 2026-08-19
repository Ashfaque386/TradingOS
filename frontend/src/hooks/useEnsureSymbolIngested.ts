"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";

const INITIAL_BACKFILL_DAYS = 730; // matches src/data/ingest/scheduled_sync.py's own default
const POLL_INTERVAL_MS = 3_000;
const POLL_TIMEOUT_MS = 120_000;

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Real symbol search-and-select: before showing data for a symbol that isn't already in the
 * local data lake, fetches it on demand via the existing managed Upstox V3/yfinance
 * failover ingestion path (`POST /market/ingest/trigger`, SA/PM/RM-gated) rather than only ever
 * offering the handful of symbols someone happened to manually ingest before. Already-cached
 * symbols resolve immediately with no network round trip beyond the once-cached symbols list. */
export function useEnsureSymbolIngested() {
  const queryClient = useQueryClient();
  const symbolsQuery = useQuery({ queryKey: ["market-symbols"], queryFn: api.symbols });
  const [status, setStatus] = useState<"idle" | "ingesting" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  async function ensure(symbol: string): Promise<boolean> {
    if ((symbolsQuery.data ?? []).includes(symbol)) return true;

    setStatus("ingesting");
    setError(null);
    try {
      const end = new Date();
      const start = new Date(end.getTime() - INITIAL_BACKFILL_DAYS * 86_400_000);
      const trigger = await api.triggerIngest({
        source: "managed",
        symbols: [symbol],
        start: isoDate(start),
        end: isoDate(end),
      });

      let job = await api.ingestJobStatus(trigger.job_id);
      const deadline = Date.now() + POLL_TIMEOUT_MS;
      while (job.status === "Running" && Date.now() < deadline) {
        await sleep(POLL_INTERVAL_MS);
        job = await api.ingestJobStatus(trigger.job_id);
      }

      if (job.status !== "Completed") {
        setStatus("error");
        setError(job.error ?? `Timed out fetching real historical data for ${symbol}.`);
        return false;
      }

      await queryClient.invalidateQueries({ queryKey: ["market-symbols"] });
      setStatus("idle");
      return true;
    } catch (e) {
      setStatus("error");
      setError(
        e instanceof ApiError && e.status === 403
          ? "This symbol isn't loaded yet — ask a System Administrator, Portfolio Manager, or Risk Manager to load it."
          : e instanceof Error
            ? e.message
            : `Failed to fetch real historical data for ${symbol}.`,
      );
      return false;
    }
  }

  return { ensure, status, error, knownSymbols: symbolsQuery.data ?? [] };
}
