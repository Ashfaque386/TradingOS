"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useBacktestJob } from "@/hooks/useBacktestJob";
import { GlassCard } from "@/components/ui/glass-card";
import { CodeDiff } from "./code-diff";
import { EquityCurveChart } from "./equity-curve-chart";
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
    return <div className="h-64 animate-pulse rounded-2xl bg-white/5" />;
  }
  const strategy = detailQuery.data;

  return (
    <div className="flex flex-col gap-4">
      <GlassCard eyebrow={strategy.status} title={strategy.name}>
        <p className="text-xs leading-relaxed text-zinc-400">
          {strategy.hypothesis ?? "No hypothesis recorded."}
        </p>
        <div className="mt-3 flex flex-wrap gap-1.5 text-[10px] text-zinc-500">
          <span className="rounded-full bg-white/5 px-2 py-0.5">{strategy.asset_class}</span>
          <span className="rounded-full bg-white/5 px-2 py-0.5">{strategy.style}</span>
          {strategy.universe?.map((sym) => (
            <span key={sym} className="rounded-full bg-cyan-400/10 px-2 py-0.5 text-cyan-300">
              {sym}
            </span>
          ))}
        </div>
      </GlassCard>

      <GlassCard eyebrow="Code Review" title="Version Diff">
        {strategy.versions.length === 0 ? (
          <p className="text-xs text-zinc-500">No code generated yet.</p>
        ) : (
          <>
            <div className="mb-3 flex flex-wrap items-center gap-2 text-[11px]">
              {strategy.versions.map((v) => (
                <span key={v.id} className={cn("rounded-full bg-white/5 px-2 py-1", VALIDATION_COLOR[v.validation_status] ?? "text-zinc-400")}>
                  v{v.version_no} · {v.validation_status}
                </span>
              ))}
            </div>
            <div className="mb-3 flex items-center gap-2 text-[11px] text-zinc-500">
              <select
                className="rounded-md border border-white/10 bg-black/30 px-2 py-1 text-zinc-300"
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
                className="rounded-md border border-white/10 bg-black/30 px-2 py-1 text-zinc-300"
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
              <pre className="max-h-[300px] overflow-auto rounded-xl border border-white/5 bg-black/40 p-3 font-mono text-[11px] text-zinc-400">
                {strategy.versions.length > 0
                  ? "Pick two versions above to see a diff, or view the latest code below."
                  : ""}
              </pre>
            )}
          </>
        )}
      </GlassCard>

      <GlassCard
        eyebrow="Sandbox"
        title="Backtest"
        action={
          <button
            onClick={() => trigger.mutate()}
            disabled={trigger.isPending || jobRunning || !strategy.current_version_id}
            className="flex items-center gap-1.5 rounded-lg bg-gradient-to-r from-cyan-500 to-purple-500 px-3 py-1.5 text-[11px] font-semibold text-black transition hover:brightness-110 disabled:opacity-40"
          >
            <Play className="h-3 w-3" />
            {jobRunning ? "Running…" : "Run Backtest"}
          </button>
        }
      >
        {jobRunning && (
          <p className="mb-3 text-[11px] text-cyan-300">
            Executing real vectorbt backtest in the sandbox against real historical data — cold
            runs take ~60-90s (numba JIT compiles fresh each time).
          </p>
        )}
        {jobQuery.data?.status === "Failed" && (
          <p className="mb-3 text-[11px] text-rose-400">Backtest failed: {jobQuery.data.error}</p>
        )}

        {strategy.backtests.length === 0 ? (
          <p className="text-xs text-zinc-500">No backtests run yet.</p>
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
                      ? "bg-white/10 text-zinc-100"
                      : "bg-white/5 text-zinc-500 hover:text-zinc-300",
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
      </GlassCard>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-white/[0.03] p-2 text-center">
      <div className="font-mono-tabular text-sm font-semibold text-zinc-100">{value}</div>
      <div className="text-[9px] uppercase tracking-wider text-zinc-500">{label}</div>
    </div>
  );
}
