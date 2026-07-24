"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

/** Polls a real backtest job until it leaves "Running" -- cold sandbox runs take ~60-90s
 * (vectorbt's numba JIT compiles fresh per subprocess), so this is a job/poll pattern rather
 * than a synchronous request the frontend would have to hold open. */
export function useBacktestJob(jobId: string | null) {
  return useQuery({
    queryKey: ["backtest-job", jobId],
    queryFn: () => api.backtestJobStatus(jobId!),
    enabled: !!jobId,
    refetchInterval: (query) => (query.state.data?.status === "Running" ? 3_000 : false),
  });
}
