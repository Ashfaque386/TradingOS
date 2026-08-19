"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Play, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useBacktestJob } from "@/hooks/useBacktestJob";
import { useEnsureSymbolIngested } from "@/hooks/useEnsureSymbolIngested";
import { Button } from "@/components/ui/button";
import { Gated } from "@/components/ui/gated";
import { SymbolCombobox } from "@/components/market/symbol-combobox";

const inputClass = "rounded-md border border-card-edge bg-bg px-1.5 py-1 text-[10px] text-text";

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
 * refetchInterval naturally stops polling once the job leaves "Running".
 *
 * UPDATE: the single shared trigger component -- review-panel.tsx (Strategy Detail page) used to
 * hand-roll its own separate button/mutation/poll here, which never invalidated `detailQuery`
 * on completion (it relied on a `refetchInterval` gated by `jobRunning`, which stopped polling
 * the instant the job completed, before the just-completed row could be re-fetched). Reusing
 * this component there fixes that for free -- there's now only one poller. Also carries the
 * optional date-range/capital inputs (blank = the backend's own existing defaults), previously
 * not configurable or visible anywhere in the UI despite `BacktestResult.date_from/date_to/
 * initial_capital` always being real, persisted values. */
export function RunBacktestButton({
  strategyId,
  disabled,
  label = "Run New Backtest",
  onCompleted,
}: {
  strategyId: string;
  disabled?: boolean;
  label?: string;
  onCompleted: (backtestId: string) => void;
}) {
  const queryClient = useQueryClient();
  const [jobId, setJobId] = useState<string | null>(null);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [capital, setCapital] = useState("");
  const [symbol, setSymbol] = useState("");
  const [pendingSymbol, setPendingSymbol] = useState<string | null>(null);
  const jobQuery = useBacktestJob(jobId);
  const jobRunning = jobQuery.data?.status === "Running";
  const notifiedJobIdRef = useRef<string | null>(null);

  // Real symbol search-and-select: overriding to a symbol not already in the local data lake
  // fetches it on demand (real Upstox V3/yfinance failover ingestion) before it can be used,
  // rather than only ever offering whatever few symbols happened to be manually ingested before.
  const { ensure, status: ingestStatus, error: ingestError } = useEnsureSymbolIngested();

  async function handleSymbolSelect(newSymbol: string) {
    setPendingSymbol(newSymbol);
    const ok = await ensure(newSymbol);
    setPendingSymbol(null);
    if (ok) setSymbol(newSymbol);
  }

  const trigger = useMutation({
    mutationFn: () =>
      api.triggerBacktest(strategyId, {
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        initial_capital: capital ? Number(capital) : undefined,
        symbol: symbol || undefined,
      }),
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
      <div className="flex flex-col items-end gap-1.5">
        <div className="flex items-center gap-1">
          <div className="relative">
            <SymbolCombobox
              value={symbol || null}
              onSelect={handleSymbolSelect}
              disabled={ingestStatus === "ingesting"}
              placeholder="Strategy's own symbol"
              className="w-[130px]"
            />
            {symbol && (
              <button
                type="button"
                onClick={() => setSymbol("")}
                title="Clear override -- use the strategy's own symbol"
                aria-label="Clear symbol override"
                className="absolute right-1 top-1/2 -translate-y-1/2 text-text-faint hover:text-text"
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </div>
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            title="Window start (defaults to 365 days before the end date)"
            className={`${inputClass} w-[112px]`}
          />
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            title="Window end (defaults to the last date this symbol has ingested data for)"
            className={`${inputClass} w-[112px]`}
          />
          <input
            type="number"
            min="1"
            step="1000"
            placeholder="₹1,00,000"
            value={capital}
            onChange={(e) => setCapital(e.target.value)}
            title="Starting capital (defaults to ₹1,00,000)"
            className={`${inputClass} w-[90px]`}
          />
        </div>
        <Button
          onClick={() => trigger.mutate()}
          disabled={disabled || trigger.isPending || jobRunning || pendingSymbol !== null}
          className="px-3 py-1.5 text-[11px]"
        >
          <Play className="h-3 w-3" />
          {jobRunning ? "Running…" : label}
        </Button>
        {ingestStatus === "ingesting" && pendingSymbol && (
          <p className="max-w-[220px] text-right text-[10px] uppercase tracking-wider text-text-faint">
            Fetching real data for {pendingSymbol}…
          </p>
        )}
        {ingestStatus === "error" && ingestError && (
          <p className="max-w-[220px] text-right text-[10px] text-down">{ingestError}</p>
        )}
        {jobQuery.data?.status === "Failed" && (
          <p className="max-w-[220px] text-right text-[10px] text-down">
            Backtest failed: {jobQuery.data.error}
          </p>
        )}
        {trigger.isError && (
          <p className="max-w-[220px] text-right text-[10px] text-down">
            Couldn&apos;t start: {trigger.error.message}
          </p>
        )}
      </div>
    </Gated>
  );
}
