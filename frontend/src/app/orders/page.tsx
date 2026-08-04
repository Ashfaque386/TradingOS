"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { RequireAuth } from "@/lib/auth";
import { TopBar } from "@/components/layout/top-bar";
import { GlassCard } from "@/components/ui/glass-card";
import { OrdersTable } from "@/components/orders/orders-table";
import { TradesTable } from "@/components/orders/trades-table";

/**
 * REL-018 E18.1/E18.2: Live Trade & Order Monitoring -- the one dashboard gap the 2026-08-01
 * audit found that wasn't just a missing UI: `ORDERS`/`TRADES` (DB-008/009) have been real
 * Postgres tables since Phase 1, but no endpoint anywhere ever listed them for real (live)
 * trading before this release (src/api/routers/orders.py). Everything below is real: 2 real
 * orders exist in this environment today (both CANCELLED by the kill switch during an earlier
 * chaos-engineering test), 0 real trades yet -- honestly shown as empty, not faked.
 */
function LiveTradeMonitoringView() {
  const [selectedStrategyId, setSelectedStrategyId] = useState<string>("");

  const strategiesQuery = useQuery({ queryKey: ["strategies"], queryFn: api.strategies });
  // `?? []` creates a fresh array reference every render when .data is undefined, which would
  // otherwise defeat the useMemo hooks below that depend on `strategies`/`trades` -- memoized
  // here too so those dependencies are stable across renders where the underlying data hasn't
  // actually changed.
  const strategies = useMemo(() => strategiesQuery.data ?? [], [strategiesQuery.data]);

  const ordersQuery = useQuery({
    queryKey: ["orders", selectedStrategyId],
    queryFn: () => api.orders(selectedStrategyId || undefined),
    refetchInterval: 15_000,
  });
  const tradesQuery = useQuery({
    queryKey: ["trades", selectedStrategyId],
    queryFn: () => api.trades(selectedStrategyId || undefined),
    refetchInterval: 15_000,
  });
  const latencyQuery = useQuery({
    queryKey: ["orders-execution-latency"],
    queryFn: api.executionLatency,
    refetchInterval: 30_000,
  });

  const orders = ordersQuery.data ?? [];
  const trades = useMemo(() => tradesQuery.data ?? [], [tradesQuery.data]);

  const strategyName = useMemo(() => {
    const byId = new Map(strategies.map((s) => [s.id, s.name]));
    return (id: string) => byId.get(id) ?? id.slice(0, 8);
  }, [strategies]);

  const attribution = useMemo(() => {
    const rows = new Map<string, { trades: number; netPnl: number }>();
    for (const t of trades) {
      const row = rows.get(t.strategy_id) ?? { trades: 0, netPnl: 0 };
      row.trades += 1;
      row.netPnl += t.net_pnl ?? 0;
      rows.set(t.strategy_id, row);
    }
    return [...rows.entries()].sort((a, b) => b[1].netPnl - a[1].netPnl);
  }, [trades]);

  const totalNetPnl = trades.reduce((sum, t) => sum + (t.net_pnl ?? 0), 0);
  const latency = latencyQuery.data;

  return (
    <main className="mx-auto flex w-full max-w-[1440px] flex-1 flex-col gap-4 p-6 sm:p-8">
      <GlassCard eyebrow="Filter" title="Strategy">
        <select
          value={selectedStrategyId}
          onChange={(e) => setSelectedStrategyId(e.target.value)}
          className="rounded-md border border-white/10 bg-black/30 px-2.5 py-1.5 text-xs text-zinc-200"
        >
          <option value="">All strategies</option>
          {strategies.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name} ({s.status})
            </option>
          ))}
        </select>
      </GlassCard>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <GlassCard eyebrow="Live" title="Total Net P&L">
          <p
            className={`text-2xl font-semibold font-mono-tabular ${
              totalNetPnl >= 0 ? "text-emerald-300" : "text-rose-400"
            }`}
          >
            {trades.length > 0 ? `₹${totalNetPnl.toFixed(2)}` : "—"}
          </p>
          <p className="mt-1 text-[11px] text-zinc-500">
            Across {trades.length} real fill{trades.length === 1 ? "" : "s"}
          </p>
        </GlassCard>

        <GlassCard eyebrow="Live" title="Orders Placed">
          <p className="text-2xl font-semibold font-mono-tabular text-zinc-200">
            {orders.length}
          </p>
          <p className="mt-1 text-[11px] text-zinc-500">
            {orders.filter((o) => o.status === "REJECTED" || o.status === "CANCELLED").length}{" "}
            rejected/cancelled
          </p>
        </GlassCard>

        <GlassCard eyebrow="NFR-02" title="Dispatch Latency (this process)">
          {latencyQuery.isLoading ? (
            <div className="h-7 animate-pulse rounded-lg bg-white/5" />
          ) : latency && latency.sample_count > 0 ? (
            <>
              <p className="text-2xl font-semibold font-mono-tabular text-zinc-200">
                {latency.avg_ms!.toFixed(2)}ms
              </p>
              <p className="mt-1 text-[11px] text-zinc-500">
                Avg over {latency.sample_count} real dispatch{latency.sample_count === 1 ? "" : "es"}
              </p>
            </>
          ) : (
            <p className="text-xs text-zinc-500">
              No orders dispatched in this app process yet — this is a real, live, in-process
              histogram (not a database query), so it resets on every restart.
            </p>
          )}
        </GlassCard>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <GlassCard eyebrow="Real Ledger" title="Order History">
          {ordersQuery.isLoading ? (
            <div className="h-40 animate-pulse rounded-xl bg-white/5" />
          ) : (
            <OrdersTable orders={orders} />
          )}
        </GlassCard>

        <GlassCard eyebrow="Real Ledger" title="Recent Fills">
          {tradesQuery.isLoading ? (
            <div className="h-40 animate-pulse rounded-xl bg-white/5" />
          ) : (
            <TradesTable trades={trades} />
          )}
        </GlassCard>
      </div>

      <GlassCard eyebrow="Attribution" title="Net P&L by Strategy">
        {attribution.length === 0 ? (
          <p className="text-xs text-zinc-500">No real trades to attribute yet.</p>
        ) : (
          <div className="overflow-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="text-zinc-500">
                  <th className="pb-2 font-medium">Strategy</th>
                  <th className="pb-2 text-right font-medium">Trades</th>
                  <th className="pb-2 text-right font-medium">Net P&amp;L</th>
                </tr>
              </thead>
              <tbody>
                {attribution.map(([strategyId, row]) => (
                  <tr key={strategyId} className="border-t border-white/5">
                    <td className="py-2 text-zinc-200">{strategyName(strategyId)}</td>
                    <td className="py-2 text-right font-mono-tabular text-zinc-300">
                      {row.trades}
                    </td>
                    <td
                      className={`py-2 text-right font-mono-tabular font-medium ${
                        row.netPnl >= 0 ? "text-emerald-300" : "text-rose-400"
                      }`}
                    >
                      ₹{row.netPnl.toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>
    </main>
  );
}

export default function OrdersPage() {
  return (
    <RequireAuth>
      <TopBar connected={false} subtitle="Live Trade & Order Monitoring — Real Capital Only" />
      <LiveTradeMonitoringView />
    </RequireAuth>
  );
}
