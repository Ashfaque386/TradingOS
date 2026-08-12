"use client";

import { cn } from "@/lib/utils";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import type { BrokerOrder, PaperTrade } from "@/lib/api";

interface UnifiedRow {
  key: string;
  source: "Paper" | "Live";
  time: string | null;
  symbol: string;
  side: "BUY" | "SELL";
  quantity: number;
  price: number | null;
  status: string;
}

/** REL-036: merges two already-real, independent data sources client-side -- the real seeded
 * Paper account's own fills (`paper_trades`, already time-stamped) and the real broker's own
 * order book (`GET /broker/order-book`, a real Zerodha/Upstox read, never a locally-placed
 * order -- BrokerAdapter has no place/modify/cancel method anywhere in this codebase). No new
 * backend join, no write path. `BrokerOrder` carries no timestamp (the broker API itself doesn't
 * return one for the order-book listing), so Live rows show "--" for Time and are listed after
 * the time-sorted Paper rows rather than fabricating an ordering. */
export function UnifiedOrderHistory({
  paper,
  live,
}: {
  paper: PaperTrade[];
  live: BrokerOrder[];
}) {
  const paperRows: UnifiedRow[] = [...paper]
    .sort((a, b) => new Date(b.executed_at).getTime() - new Date(a.executed_at).getTime())
    .map((t) => ({
      key: `paper-${t.id}`,
      source: "Paper" as const,
      time: t.executed_at,
      symbol: t.symbol,
      side: t.side,
      quantity: t.filled_quantity,
      price: t.fill_price,
      status: "FILLED",
    }));

  const liveRows: UnifiedRow[] = live.map((o) => ({
    key: `live-${o.broker_order_id}`,
    source: "Live" as const,
    time: null,
    symbol: o.symbol,
    side: o.side,
    quantity: o.filled_quantity || o.quantity,
    price: o.average_price ?? o.limit_price,
    status: o.status,
  }));

  const rows = [...paperRows, ...liveRows];

  if (rows.length === 0) {
    return (
      <div className="flex h-[140px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-card-edge text-center">
        <p className="text-xs text-text-faint">No orders in the selected scope yet.</p>
      </div>
    );
  }

  return (
    <div className="max-h-[420px] overflow-auto">
      <Table className="text-xs">
        <TableHeader className="sticky top-0 z-10 bg-panel">
          <TableRow className="text-text-faint hover:bg-transparent">
            <TableHead className="h-auto px-0 pb-2 font-medium">Source</TableHead>
            <TableHead className="h-auto px-0 pb-2 font-medium">Time</TableHead>
            <TableHead className="h-auto px-0 pb-2 font-medium">Symbol</TableHead>
            <TableHead className="h-auto px-0 pb-2 font-medium">Side</TableHead>
            <TableHead className="h-auto px-0 pb-2 text-right font-medium">Qty</TableHead>
            <TableHead className="h-auto px-0 pb-2 text-right font-medium">Price</TableHead>
            <TableHead className="h-auto px-0 pb-2 font-medium">Status</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.key} className="border-card-edge align-top">
              <TableCell className="px-0 py-row-dense">
                <Badge variant={row.source === "Paper" ? "secondary" : "default"}>
                  {row.source}
                </Badge>
              </TableCell>
              <TableCell className="px-0 py-row-dense whitespace-nowrap font-mono-tabular text-text-faint">
                {row.time
                  ? new Date(row.time).toLocaleString("en-IN", {
                      timeZone: "Asia/Kolkata",
                      day: "2-digit",
                      month: "short",
                      hour: "2-digit",
                      minute: "2-digit",
                    })
                  : "—"}
              </TableCell>
              <TableCell className="px-0 py-row-dense font-medium text-text">
                {row.symbol}
              </TableCell>
              <TableCell
                className={cn(
                  "px-0 py-row-dense font-medium",
                  row.side === "BUY" ? "text-brand-via" : "text-brand-to",
                )}
              >
                {row.side}
              </TableCell>
              <TableCell className="px-0 py-row-dense text-right font-mono-tabular text-text-dim">
                {row.quantity}
              </TableCell>
              <TableCell className="px-0 py-row-dense text-right font-mono-tabular text-text-faint">
                {row.price !== null ? row.price.toFixed(2) : "—"}
              </TableCell>
              <TableCell className="px-0 py-row-dense text-text-dim">{row.status}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
