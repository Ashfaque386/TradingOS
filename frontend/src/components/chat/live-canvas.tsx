"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { EquityCurveChart } from "@/components/strategies/equity-curve-chart";

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-IN", { hour12: false });
}

const VALIDATION_COLOR: Record<string, string> = {
  Passed: "text-emerald-400",
  Failed: "text-rose-400",
  Pending: "text-amber-400",
};

/** Side-by-side artifact viewer per §2.5 -- polls the real /canvas/state composite (see
 * src/api/routers/canvas.py) so whatever the agents most recently produced (generated code, a
 * backtest, an activity log line) shows up here without the frontend guessing what's newest. */
export function LiveCanvas() {
  const stateQuery = useQuery({
    queryKey: ["canvas-state"],
    queryFn: api.canvasState,
    refetchInterval: 5_000,
  });

  const equityQuery = useQuery({
    queryKey: ["canvas-equity-curve", stateQuery.data?.latest_backtest?.backtest_id],
    queryFn: () => api.equityCurve(stateQuery.data!.latest_backtest!.backtest_id),
    enabled: !!stateQuery.data?.latest_backtest?.has_equity_curve,
  });

  const state = stateQuery.data;

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto">
      <Section eyebrow="Generated" title="Latest Strategy Code">
        {state?.latest_code ? (
          <>
            <div className="mb-2 flex items-center justify-between text-[11px]">
              <span className="text-zinc-300">
                {state.latest_code.strategy_name} · v{state.latest_code.version_no}
              </span>
              <span className={VALIDATION_COLOR[state.latest_code.validation_status] ?? "text-zinc-500"}>
                {state.latest_code.validation_status}
              </span>
            </div>
            <pre className="max-h-[220px] overflow-auto rounded-lg bg-black/40 p-3 font-mono text-[10.5px] leading-relaxed text-zinc-400">
              {state.latest_code.python_code}
            </pre>
            <p className="mt-1.5 text-[10px] text-zinc-600">
              Generated {formatTime(state.latest_code.created_at)}
            </p>
          </>
        ) : (
          <Empty text="No strategy code generated yet." />
        )}
      </Section>

      <Section eyebrow="Sandbox" title="Latest Backtest">
        {state?.latest_backtest ? (
          <>
            <p className="mb-2 text-[11px] text-zinc-300">
              {state.latest_backtest.strategy_name}
            </p>
            <div className="mb-3 grid grid-cols-3 gap-2">
              <Metric label="Sharpe" value={state.latest_backtest.sharpe_ratio?.toFixed(2) ?? "—"} />
              <Metric
                label="Max DD"
                value={
                  state.latest_backtest.max_drawdown !== null
                    ? `${(state.latest_backtest.max_drawdown * 100).toFixed(1)}%`
                    : "—"
                }
              />
              <Metric label="Trades" value={state.latest_backtest.total_trades?.toString() ?? "—"} />
            </div>
            <EquityCurveChart points={equityQuery.data ?? []} />
          </>
        ) : (
          <Empty text="No backtests run yet." />
        )}
      </Section>

      <Section eyebrow="Live" title="Latest Agent Activity">
        {state?.latest_agent_activity ? (
          <div className="rounded-lg bg-black/30 p-3 font-mono text-[11px] text-zinc-400">
            <span className="font-semibold text-purple-300">
              [{state.latest_agent_activity.node}]
            </span>{" "}
            {state.latest_agent_activity.message}
            <div className="mt-1 text-[9px] text-zinc-600">
              {formatTime(state.latest_agent_activity.created_at)}
            </div>
          </div>
        ) : (
          <Empty text="No agent activity recorded yet." />
        )}
      </Section>
    </div>
  );
}

function Section({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="glass-panel rounded-xl p-3.5">
      <div className="mb-2">
        <div className="text-[9px] font-medium uppercase tracking-[0.16em] text-zinc-500">
          {eyebrow}
        </div>
        <div className="text-xs font-medium text-zinc-200">{title}</div>
      </div>
      {children}
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="flex h-16 items-center justify-center rounded-lg border border-dashed border-white/10">
      <p className="text-[11px] text-zinc-600">{text}</p>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-white/[0.03] p-2 text-center">
      <div className="font-mono-tabular text-xs font-semibold text-zinc-100">{value}</div>
      <div className="text-[8px] uppercase tracking-wider text-zinc-500">{label}</div>
    </div>
  );
}
