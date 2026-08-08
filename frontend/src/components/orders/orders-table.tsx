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
import type { LiveOrder } from "@/lib/api";

const STATUS_COLOR: Record<string, string> = {
  FILLED: "text-up",
  PENDING: "text-warn",
  CANCELLED: "text-text-faint",
  REJECTED: "text-down",
};

export function OrdersTable({ orders }: { orders: LiveOrder[] }) {
  if (orders.length === 0) {
    return (
      <div className="flex h-[140px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-card-edge text-center">
        <p className="text-xs text-text-faint">No real orders recorded yet.</p>
      </div>
    );
  }

  return (
    <div className="max-h-[420px] overflow-auto">
      <Table className="text-xs">
        <TableHeader className="sticky top-0 z-10 bg-panel">
          <TableRow className="text-text-faint hover:bg-transparent">
            <TableHead className="h-auto px-0 pb-2 font-medium">Time</TableHead>
            <TableHead className="h-auto px-0 pb-2 font-medium">Symbol</TableHead>
            <TableHead className="h-auto px-0 pb-2 font-medium">Side</TableHead>
            <TableHead className="h-auto px-0 pb-2 font-medium">Type</TableHead>
            <TableHead className="h-auto px-0 pb-2 text-right font-medium">Qty</TableHead>
            <TableHead className="h-auto px-0 pb-2 text-right font-medium">Limit</TableHead>
            <TableHead className="h-auto px-0 pb-2 font-medium">Status</TableHead>
            <TableHead className="h-auto px-0 pb-2 text-right font-medium">Latency</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {orders.map((o) => (
            <TableRow key={o.id} className="border-card-edge align-top">
              <TableCell className="px-0 py-row-dense whitespace-nowrap font-mono-tabular text-text-faint">
                {new Date(o.requested_at).toLocaleString("en-IN", {
                  timeZone: "Asia/Kolkata",
                  day: "2-digit",
                  month: "short",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </TableCell>
              <TableCell className="px-0 py-row-dense font-medium text-text">{o.symbol}</TableCell>
              <TableCell
                className={cn(
                  "px-0 py-row-dense font-medium",
                  o.side === "BUY" ? "text-brand-via" : "text-brand-to",
                )}
              >
                {o.side}
              </TableCell>
              <TableCell className="px-0 py-row-dense text-text-dim">{o.order_type}</TableCell>
              <TableCell className="px-0 py-row-dense text-right font-mono-tabular text-text-dim">
                {o.quantity}
              </TableCell>
              <TableCell className="px-0 py-row-dense text-right font-mono-tabular text-text-faint">
                {o.limit_price !== null ? o.limit_price.toFixed(2) : "—"}
              </TableCell>
              <TableCell className="px-0 py-row-dense whitespace-normal">
                <span className={cn("font-medium", STATUS_COLOR[o.status] ?? "text-text-dim")}>
                  {o.status}
                </span>
                {o.rejection_reason && (
                  <div className="mt-0.5 max-w-[220px] text-[10px] leading-tight text-text-faint">
                    {o.rejection_reason}
                  </div>
                )}
              </TableCell>
              <TableCell className="px-0 py-row-dense text-right font-mono-tabular text-text-faint">
                {o.latency_ms !== null ? `${o.latency_ms}ms` : "—"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
