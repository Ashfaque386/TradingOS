"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useBacktestJob } from "@/hooks/useBacktestJob";
import { Button } from "@/components/ui/button";
import { Gated } from "@/components/ui/gated";

/** REL-041: wired identically to the Strategies page's existing trigger
 * (components/strategies/review-panel.tsx) -- this page had no way to launch a new run at all,
 * only to view past ones. On completion, invalidates every query keyed on this strategy/backtest
 * so the new run appears without a manual refresh.
 *
 * `notifiedJobIdRef` guards `onCompleted` to fire exactly once per completed job -- the polled
 * job-status query can re-render with the same "Completed" data (window refocus, cache
 * revalidation) well after the job itself finished. No setState happens in the effect itself
 * (only the query-cache/callback side effects the effect is meant for) -- `jobId` is left as-is
 * rather than reset, since the ref already prevents re-notification and useBacktestJob's own
 * refetchInterval naturally stops polling once the job leaves "Running". */
export function RunBacktestButton({
  strategyId,
  disabled,
  onCompleted,
}: {
  strategyId: string;
  disabled?: boolean;
  onCompleted: (backtestId: string) => void;
}) {
  const queryClient = useQueryClient();
  const [jobId, setJobId] = useState<string | null>(null);
  const jobQuery = useBacktestJob(jobId);
  const jobRunning = jobQuery.data?.status === "Running";
  const notifiedJobIdRef = useRef<string | null>(null);

  const trigger = useMutation({
    mutationFn: () => api.triggerBacktest(strategyId),
    onSuccess: (res) => setJobId(res.job_id),
  });

  useEffect(() => {
    if (
      jobId &&
      jobQuery.data?.status === "Completed" &&
      jobQuery.data.backtest_result_id &&
      notifiedJobIdRef.current !== jobId
    ) {
      notifiedJobIdRef.current = jobId;
      queryClient.invalidateQueries({ queryKey: ["strategy", strategyId] });
      queryClient.invalidateQueries({ queryKey: ["strategies"] });
      queryClient.invalidateQueries({ queryKey: ["latest-backtests"] });
      onCompleted(jobQuery.data.backtest_result_id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, jobQuery.data?.status, jobQuery.data?.backtest_result_id]);

  return (
    <Gated permission="triggerBacktest">
      <Button
        onClick={() => trigger.mutate()}
        disabled={disabled || trigger.isPending || jobRunning}
        className="px-3 py-1.5 text-[11px]"
      >
        <Play className="h-3 w-3" />
        {jobRunning ? "Running…" : "Run New Backtest"}
      </Button>
      {jobQuery.data?.status === "Failed" && (
        <p className="mt-1.5 text-[10px] text-down">Backtest failed: {jobQuery.data.error}</p>
      )}
      {trigger.isError && (
        <p className="mt-1.5 max-w-[220px] text-[10px] text-down">
          Couldn&apos;t start: {trigger.error.message}
        </p>
      )}
    </Gated>
  );
}
