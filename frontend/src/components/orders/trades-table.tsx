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
import type { LiveTrade } from "@/lib/api";

export function TradesTable({ trades }: { trades: LiveTrade[] }) {
  if (trades.length === 0) {
    return (
      <div className="flex h-[140px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-card-edge text-center">
        <p className="text-xs text-text-faint">No real fills recorded yet.</p>
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
            <TableHead className="h-auto px-0 pb-2 text-right font-medium">Qty</TableHead>
            <TableHead className="h-auto px-0 pb-2 text-right font-medium">Price</TableHead>
            <TableHead className="h-auto px-0 pb-2 text-right font-medium">Fees</TableHead>
            <TableHead className="h-auto px-0 pb-2 text-right font-medium">Net P&amp;L</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {trades.map((t) => (
            <TableRow key={t.id} className="border-card-edge">
              <TableCell className="px-0 py-row-dense font-mono-tabular text-text-faint">
                {new Date(t.executed_at).toLocaleString("en-IN", {
                  timeZone: "Asia/Kolkata",
                  day: "2-digit",
                  month: "short",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </TableCell>
              <TableCell className="px-0 py-row-dense font-medium text-text">{t.symbol}</TableCell>
              <TableCell
                className={cn(
                  "px-0 py-row-dense font-medium",
                  t.side === "BUY" ? "text-brand-via" : "text-brand-to",
                )}
              >
                {t.side}
              </TableCell>
              <TableCell className="px-0 py-row-dense text-right font-mono-tabular text-text-dim">
                {t.quantity}
              </TableCell>
              <TableCell className="px-0 py-row-dense text-right font-mono-tabular text-text-dim">
                {t.price.toFixed(2)}
              </TableCell>
              <TableCell className="px-0 py-row-dense text-right font-mono-tabular text-text-faint">
                {(t.brokerage + t.stt + t.gst).toFixed(2)}
              </TableCell>
              <TableCell
                className={cn(
                  "px-0 py-row-dense text-right font-mono-tabular font-medium",
                  t.net_pnl === null
                    ? "text-text-faint"
                    : t.net_pnl >= 0
                      ? "text-up"
                      : "text-down",
                )}
              >
                {t.net_pnl !== null ? t.net_pnl.toFixed(2) : "—"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
