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
import type { PaperTrade } from "@/lib/api";

export function PaperTradesTable({ trades }: { trades: PaperTrade[] }) {
  if (trades.length === 0) {
    return (
      <div className="flex h-[140px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-card-edge text-center">
        <p className="text-xs text-text-faint">No simulated fills recorded yet.</p>
      </div>
    );
  }

  const recent = [...trades].reverse().slice(0, 25);

  return (
    <div className="max-h-[360px] overflow-auto">
      <Table className="text-xs">
        <TableHeader className="sticky top-0 z-10 bg-panel">
          <TableRow className="text-text-faint hover:bg-transparent">
            <TableHead className="h-auto px-0 pb-2 font-medium">Time</TableHead>
            <TableHead className="h-auto px-0 pb-2 font-medium">Symbol</TableHead>
            <TableHead className="h-auto px-0 pb-2 font-medium">Type</TableHead>
            <TableHead className="h-auto px-0 pb-2 font-medium">Side</TableHead>
            <TableHead className="h-auto px-0 pb-2 text-right font-medium">Filled</TableHead>
            <TableHead className="h-auto px-0 pb-2 text-right font-medium">Reference</TableHead>
            <TableHead className="h-auto px-0 pb-2 text-right font-medium">Fill</TableHead>
            <TableHead className="h-auto px-0 pb-2 text-right font-medium">Slippage</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {recent.map((t) => (
            <TableRow key={t.id} className="border-card-edge">
              <TableCell className="px-0 py-2 font-mono-tabular text-text-faint">
                {new Date(t.executed_at).toLocaleString("en-IN", {
                  timeZone: "Asia/Kolkata",
                  day: "2-digit",
                  month: "short",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </TableCell>
              <TableCell className="px-0 py-2 font-medium text-text">{t.symbol}</TableCell>
              <TableCell className="px-0 py-2 text-text-faint">{t.instrument_type}</TableCell>
              <TableCell
                className={cn(
                  "px-0 py-2 font-medium",
                  t.side === "BUY" ? "text-brand-via" : "text-brand-to",
                )}
              >
                {t.side}
              </TableCell>
              <TableCell className="px-0 py-2 text-right font-mono-tabular text-text-dim">
                {t.filled_quantity}
                {t.filled_quantity < t.requested_quantity && (
                  <span className="text-text-faint">/{t.requested_quantity}</span>
                )}
              </TableCell>
              <TableCell className="px-0 py-2 text-right font-mono-tabular text-text-faint">
                {t.reference_price.toFixed(2)}
              </TableCell>
              <TableCell className="px-0 py-2 text-right font-mono-tabular text-text-dim">
                {t.fill_price.toFixed(2)}
              </TableCell>
              <TableCell
                className={cn(
                  "px-0 py-2 text-right font-mono-tabular",
                  t.slippage_bps > 0 ? "text-warn" : "text-text-faint",
                )}
              >
                {t.slippage_bps.toFixed(1)}bps
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
