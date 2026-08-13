"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

/** REL-049: polls a real suggestion-review job until it leaves "Running" -- a full regeneration
 * re-enters the real agent pipeline (multiple real LLM calls, a real sandboxed backtest), same
 * order of magnitude as a real backtest job (see useBacktestJob.ts's own note), so this is a
 * job/poll pattern rather than a synchronous request the frontend would have to hold open. */
export function useSuggestionReviewJob(jobId: string | null) {
  return useQuery({
    queryKey: ["suggestion-review-job", jobId],
    queryFn: () => api.suggestionReviewJobStatus(jobId!),
    enabled: !!jobId,
    refetchInterval: (query) => (query.state.data?.status === "Running" ? 5_000 : false),
  });
}
