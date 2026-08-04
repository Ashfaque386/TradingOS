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
import { CodeDiff } from "./code-diff";
import { EquityCurveChart } from "./equity-curve-chart";
import { GoLiveGatePanel } from "./go-live-gate-panel";
import { VALIDATION_COLOR } from "./strategy-card";

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

  if (!detailQuery.data) {
    return <div className="h-64 animate-pulse rounded-2xl bg-bg" />;
  }
  const strategy = detailQuery.data;

  return (
    <div className="flex flex-col gap-4">
      <Card eyebrow={strategy.status} title={strategy.name}>
        <p className="text-xs leading-relaxed text-text-dim">
          {strategy.hypothesis ?? "No hypothesis recorded."}
        </p>
        <div className="mt-3 flex flex-wrap gap-1.5 text-[10px] text-text-faint">
          <span className="rounded-full bg-bg px-2 py-0.5">{strategy.asset_class}</span>
          <span className="rounded-full bg-bg px-2 py-0.5">{strategy.style}</span>
          {strategy.universe?.map((sym) => (
            <span key={sym} className="rounded-full bg-brand-via/10 px-2 py-0.5 text-brand-via">
              {sym}
            </span>
          ))}
        </div>
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
              <>
                <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <Metric label="Sharpe" value={selectedBacktest.sharpe_ratio?.toFixed(2) ?? "—"} />
                  <Metric
                    label="Max DD"
                    value={
                      selectedBacktest.max_drawdown !== null
                        ? `${(selectedBacktest.max_drawdown * 100).toFixed(1)}%`
                        : "—"
                    }
                  />
                  <Metric
                    label="Win Rate"
                    value={
                      selectedBacktest.win_rate !== null
                        ? `${(selectedBacktest.win_rate * 100).toFixed(0)}%`
                        : "—"
                    }
                  />
                  <Metric label="Trades" value={selectedBacktest.total_trades?.toString() ?? "—"} />
                </div>
                <EquityCurveChart points={equityCurveQuery.data ?? []} />
              </>
            )}
          </>
        )}
      </Card>

      <GoLiveGatePanel strategyId={strategyId} />
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-bg p-2 text-center">
      <div className="font-mono-tabular text-sm font-semibold text-text">{value}</div>
      <div className="text-[9px] uppercase tracking-wider text-text-faint">{label}</div>
    </div>
  );
}
