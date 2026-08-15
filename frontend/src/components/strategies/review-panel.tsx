"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useBacktestJob } from "@/hooks/useBacktestJob";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Gated } from "@/components/ui/gated";
import { VerdictPanel } from "@/components/backtests/verdict-panel";
import { FullMetricGrid } from "@/components/backtests/metric-grid";
import { CodeDiff } from "./code-diff";
import { EquityCurveChart, buildBenchmarkOverlay } from "./equity-curve-chart";
import { DrawdownChart } from "./drawdown-chart";
import { GoLiveGatePanel } from "./go-live-gate-panel";
import { OptionLegsPanel } from "./option-legs-panel";
import { ResearchContextPanel } from "./research-context-panel";
import { StrategyLogicPanel } from "./strategy-logic-panel";
import { SuggestionPanel } from "./suggestion-panel";
import { VALIDATION_COLOR } from "./strategy-card";

const BENCHMARK_SYMBOL = "^NSEI";

export function ReviewPanel({ strategyId }: { strategyId: string }) {
  const [jobId, setJobId] = useState<string | null>(null);
  const [selectedBacktestId, setSelectedBacktestId] = useState<string | null>(null);
  const [diffA, setDiffA] = useState<number | null>(null);
  const [diffB, setDiffB] = useState<number | null>(null);

  const jobQuery = useBacktestJob(jobId);
  const jobRunning = jobQuery.data?.status === "Running";

  const detailQuery = useQuery({
    queryKey: ["strategy", strategyId],
    queryFn: () => api.strategy(strategyId),
    // Keeps polling the strategy while a backtest job is in flight so the new BacktestResult
    // row shows up as soon as the job finishes -- no effect-driven "did the job just complete"
    // logic needed, this just naturally converges once the row exists.
    refetchInterval: jobRunning ? 3_000 : false,
  });

  const trigger = useMutation({
    mutationFn: () => api.triggerBacktest(strategyId),
    onSuccess: (res) => {
      setJobId(res.job_id);
      setSelectedBacktestId(null); // fall back to "most recent" once the new one lands
    },
  });

  const codeAQuery = useQuery({
    queryKey: ["version-code", strategyId, diffA],
    queryFn: () => api.strategyVersionCode(strategyId, diffA!),
    enabled: diffA !== null,
  });
  const codeBQuery = useQuery({
    queryKey: ["version-code", strategyId, diffB],
    queryFn: () => api.strategyVersionCode(strategyId, diffB!),
    enabled: diffB !== null,
  });

  const backtests = detailQuery.data?.backtests ?? [];
  const effectiveBacktestId = selectedBacktestId ?? backtests[0]?.id ?? null;
  const selectedBacktest = backtests.find((b) => b.id === effectiveBacktestId) ?? null;

  const equityCurveQuery = useQuery({
    queryKey: ["equity-curve", effectiveBacktestId],
    queryFn: () => api.equityCurve(effectiveBacktestId!),
    enabled: !!effectiveBacktestId && !!selectedBacktest?.has_equity_curve,
  });
  const tradesQuery = useQuery({
    queryKey: ["backtest-trades", effectiveBacktestId],
    queryFn: () => api.backtestTrades(effectiveBacktestId!),
    enabled: !!effectiveBacktestId,
  });
  const benchmarkQuery = useQuery({
    queryKey: ["ohlcv", BENCHMARK_SYMBOL],
    queryFn: () => api.ohlcv(BENCHMARK_SYMBOL),
  });

  if (!detailQuery.data) {
    return <div className="h-64 animate-pulse rounded-2xl bg-bg" />;
  }
  const strategy = detailQuery.data;
  const currentVersion = strategy.versions.find((v) => v.id === strategy.current_version_id) ?? null;
  const equityCurvePoints = equityCurveQuery.data ?? [];
  const benchmarkOverlay = buildBenchmarkOverlay(equityCurvePoints, benchmarkQuery.data ?? []);

  return (
    <div className="flex flex-col gap-4">
      <Card eyebrow={strategy.status} title={strategy.name}>
        <p className="text-xs leading-relaxed text-text-dim">
          {strategy.hypothesis ?? "No hypothesis recorded."}
        </p>
        <div className="mt-3 flex flex-wrap gap-1.5 text-[10px] text-text-faint">
          <span className="rounded-full bg-bg px-2 py-0.5">{strategy.asset_class}</span>
          <span className="rounded-full bg-bg px-2 py-0.5">{strategy.style}</span>
          {strategy.max_drawdown_limit !== null && (
            <span className="rounded-full bg-bg px-2 py-0.5">
              Max DD limit {strategy.max_drawdown_limit.toFixed(1)}%
            </span>
          )}
          {strategy.universe?.map((sym) => (
            <span key={sym} className="rounded-full bg-brand-via/10 px-2 py-0.5 text-brand-via">
              {sym}
            </span>
          ))}
        </div>
      </Card>

      <Card eyebrow="Collaborate" title="Suggest a Change">
        <SuggestionPanel strategyId={strategyId} versions={strategy.versions} />
      </Card>

      <Card eyebrow="AI Pipeline" title="Strategy Logic">
        <StrategyLogicPanel strategy={strategy} />
      </Card>

      <Card eyebrow="AI Pipeline" title="Why This Strategy Was Proposed">
        <ResearchContextPanel strategy={strategy} />
      </Card>

      <Card eyebrow="Code Review" title="Version Diff">
        {strategy.versions.length === 0 ? (
          <p className="text-xs text-text-faint">No code generated yet.</p>
        ) : (
          <>
            <div className="mb-3 flex flex-wrap items-center gap-2 text-[11px]">
              {strategy.versions.map((v) => (
                <span key={v.id} className={cn("rounded-full bg-bg px-2 py-1", VALIDATION_COLOR[v.validation_status] ?? "text-text-dim")}>
                  v{v.version_no} · {v.validation_status}
                </span>
              ))}
            </div>
            {strategy.versions.some((v) => v.validator_feedback) && (
              <div className="mb-3 flex flex-col gap-1.5">
                {strategy.versions
                  .filter((v) => v.validator_feedback)
                  .map((v) => (
                    <div key={v.id} className="rounded-lg bg-bg p-2.5">
                      <div className="text-[9px] font-medium uppercase tracking-wider text-text-faint">
                        v{v.version_no} · Validator Feedback
                      </div>
                      <p className="mt-0.5 text-[11px] leading-relaxed text-text-dim">
                        {v.validator_feedback}
                      </p>
                    </div>
                  ))}
              </div>
            )}
            <div className="mb-3 flex items-center gap-2 text-[11px] text-text-faint">
              <select
                className="rounded-md border border-card-edge bg-bg px-2 py-1 text-text-dim"
                value={diffA ?? ""}
                onChange={(e) => setDiffA(e.target.value ? Number(e.target.value) : null)}
              >
                <option value="">Compare from…</option>
                {strategy.versions.map((v) => (
                  <option key={v.version_no} value={v.version_no}>
                    v{v.version_no}
                  </option>
                ))}
              </select>
              <span>vs</span>
              <select
                className="rounded-md border border-card-edge bg-bg px-2 py-1 text-text-dim"
                value={diffB ?? ""}
                onChange={(e) => setDiffB(e.target.value ? Number(e.target.value) : null)}
              >
                <option value="">Compare to…</option>
                {strategy.versions.map((v) => (
                  <option key={v.version_no} value={v.version_no}>
                    v{v.version_no}
                  </option>
                ))}
              </select>
            </div>
            {diffA !== null && diffB !== null && codeAQuery.data && codeBQuery.data ? (
              <CodeDiff before={codeAQuery.data.python_code} after={codeBQuery.data.python_code} />
            ) : (
              <pre className="max-h-[300px] overflow-auto rounded-xl border border-card-edge bg-bg p-3 font-mono text-[11px] text-text-dim">
                {strategy.versions.length > 0
                  ? "Pick two versions above to see a diff, or view the latest code below."
                  : ""}
              </pre>
            )}
          </>
        )}
      </Card>

      {strategy.asset_class === "F&O" && currentVersion && (
        <Card eyebrow="AI Pipeline" title="Option Legs">
          <OptionLegsPanel version={currentVersion} />
        </Card>
      )}

      <Card
        eyebrow="Sandbox"
        title="Backtest"
        action={
          <Gated permission="triggerBacktest">
            <Button
              onClick={() => trigger.mutate()}
              disabled={trigger.isPending || jobRunning || !strategy.current_version_id}
              className="px-3 py-1.5 text-[11px]"
            >
              <Play className="h-3 w-3" />
              {jobRunning ? "Running…" : "Run Backtest"}
            </Button>
          </Gated>
        }
      >
        {jobRunning && (
          <p className="mb-3 text-[11px] text-brand-via">
            Executing real vectorbt backtest in the sandbox against real historical data — cold
            runs take ~60-90s (numba JIT compiles fresh each time).
          </p>
        )}
        {jobQuery.data?.status === "Failed" && (
          <p className="mb-3 text-[11px] text-down">Backtest failed: {jobQuery.data.error}</p>
        )}
        {trigger.isError && (
          <p className="mb-3 text-[11px] text-down">Couldn&apos;t start: {trigger.error.message}</p>
        )}

        {strategy.backtests.length === 0 ? (
          <p className="text-xs text-text-faint">No backtests run yet.</p>
        ) : (
          <>
            <div className="mb-3 flex flex-wrap gap-1.5">
              {strategy.backtests.map((b) => (
                <button
                  key={b.id}
                  onClick={() => setSelectedBacktestId(b.id)}
                  className={cn(
                    "rounded-full px-2.5 py-1 text-[10px] font-medium transition-colors",
                    b.id === effectiveBacktestId
                      ? "bg-panel text-text"
                      : "bg-bg text-text-faint hover:text-text-dim",
                  )}
                >
                  {new Date(b.created_at).toLocaleDateString("en-IN")}
                </button>
              ))}
            </div>

            {selectedBacktest && (
              <div className="flex flex-col gap-4">
                <VerdictPanel backtest={selectedBacktest} />
                <FullMetricGrid backtest={selectedBacktest} />
                <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                  <EquityCurveChart
                    points={equityCurvePoints}
                    benchmark={benchmarkOverlay}
                    trades={tradesQuery.data}
                  />
                  <DrawdownChart points={equityCurvePoints} />
                </div>
              </div>
            )}
          </>
        )}
      </Card>

      <GoLiveGatePanel strategyId={strategyId} />
    </div>
  );
}
