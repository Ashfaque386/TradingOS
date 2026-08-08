"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { usePageStatus } from "@/hooks/usePageStatus";
import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
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
export default function OrdersPage() {
  const [selectedStrategyId, setSelectedStrategyId] = useState<string>("");

  usePageStatus("Live Trade & Order Monitoring — Real Capital Only", false);

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
      <Card eyebrow="Filter" title="Strategy">
        <select
          value={selectedStrategyId}
          onChange={(e) => setSelectedStrategyId(e.target.value)}
          className="rounded-md border border-card-edge bg-bg px-2.5 py-1.5 text-xs text-text"
        >
          <option value="">All strategies</option>
          {strategies.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name} ({s.status})
            </option>
          ))}
        </select>
      </Card>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Card eyebrow="Live" title="Total Net P&L">
          <p
            className={`text-2xl font-semibold font-mono-tabular ${
              totalNetPnl >= 0 ? "text-up" : "text-down"
            }`}
          >
            {trades.length > 0 ? `₹${totalNetPnl.toFixed(2)}` : "—"}
          </p>
          <p className="mt-1 text-[11px] text-text-faint">
            Across {trades.length} real fill{trades.length === 1 ? "" : "s"}
          </p>
        </Card>

        <Card eyebrow="Live" title="Orders Placed">
          <p className="text-2xl font-semibold font-mono-tabular text-text">
            {orders.length}
          </p>
          <p className="mt-1 text-[11px] text-text-faint">
            {orders.filter((o) => o.status === "REJECTED" || o.status === "CANCELLED").length}{" "}
            rejected/cancelled
          </p>
        </Card>

        <Card eyebrow="NFR-02" title="Dispatch Latency (this process)">
          {latencyQuery.isLoading ? (
            <div className="h-7 animate-pulse rounded-lg bg-bg" />
          ) : latency && latency.sample_count > 0 ? (
            <>
              <p className="text-2xl font-semibold font-mono-tabular text-text">
                {latency.avg_ms!.toFixed(2)}ms
              </p>
              <p className="mt-1 text-[11px] text-text-faint">
                Avg over {latency.sample_count} real dispatch{latency.sample_count === 1 ? "" : "es"}
              </p>
            </>
          ) : (
            <p className="text-xs text-text-faint">
              No orders dispatched in this app process yet — this is a real, live, in-process
              histogram (not a database query), so it resets on every restart.
            </p>
          )}
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card eyebrow="Real Ledger" title="Order History">
          {ordersQuery.isLoading ? (
            <div className="h-40 animate-pulse rounded-xl bg-bg" />
          ) : (
            <OrdersTable orders={orders} />
          )}
        </Card>

        <Card eyebrow="Real Ledger" title="Recent Fills">
          {tradesQuery.isLoading ? (
            <div className="h-40 animate-pulse rounded-xl bg-bg" />
          ) : (
            <TradesTable trades={trades} />
          )}
        </Card>
      </div>

      <Card eyebrow="Attribution" title="Net P&L by Strategy">
        {attribution.length === 0 ? (
          <p className="text-xs text-text-faint">No real trades to attribute yet.</p>
        ) : (
          <div className="overflow-auto">
            <Table className="text-xs">
              <TableHeader>
                <TableRow className="text-text-faint hover:bg-transparent">
                  <TableHead className="h-auto px-0 pb-2 font-medium">Strategy</TableHead>
                  <TableHead className="h-auto px-0 pb-2 text-right font-medium">Trades</TableHead>
                  <TableHead className="h-auto px-0 pb-2 text-right font-medium">Net P&amp;L</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {attribution.map(([strategyId, row]) => (
                  <TableRow key={strategyId} className="border-card-edge">
                    <TableCell className="px-0 py-row-dense text-text">{strategyName(strategyId)}</TableCell>
                    <TableCell className="px-0 py-row-dense text-right font-mono-tabular text-text-dim">
                      {row.trades}
                    </TableCell>
                    <TableCell
                      className={cn(
                        "px-0 py-row-dense text-right font-mono-tabular font-medium",
                        row.netPnl >= 0 ? "text-up" : "text-down",
                      )}
                    >
                      ₹{row.netPnl.toFixed(2)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </Card>
    </main>
  );
}
