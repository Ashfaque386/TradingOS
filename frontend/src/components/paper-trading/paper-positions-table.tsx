"use client";

import { cn, formatCompactINR } from "@/lib/utils";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { PaperPosition } from "@/lib/api";

export function PaperPositionsTable({ positions }: { positions: PaperPosition[] }) {
  if (positions.length === 0) {
    return (
      <div className="flex h-[140px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-card-edge text-center">
        <p className="text-xs text-text-faint">No paper positions yet — execute a simulated fill to start one.</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <Table className="text-xs">
        <TableHeader>
          <TableRow className="text-text-faint hover:bg-transparent">
            <TableHead className="h-auto px-0 pb-2 font-medium">Symbol</TableHead>
            <TableHead className="h-auto px-0 pb-2 text-right font-medium">Net Qty</TableHead>
            <TableHead className="h-auto px-0 pb-2 text-right font-medium">Avg Cost</TableHead>
            <TableHead className="h-auto px-0 pb-2 text-right font-medium">Realized P&amp;L</TableHead>
            <TableHead className="h-auto px-0 pb-2 text-right font-medium">Trades</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {positions.map((p) => {
            const positive = p.realized_pnl >= 0;
            return (
              <TableRow key={p.symbol} className="border-card-edge">
                <TableCell className="px-0 py-2.5 font-medium text-text">{p.symbol}</TableCell>
                <TableCell
                  className={cn(
                    "px-0 py-2.5 text-right font-mono-tabular",
                    p.net_quantity >= 0 ? "text-text-dim" : "text-down",
                  )}
                >
                  {p.net_quantity}
                </TableCell>
                <TableCell className="px-0 py-2.5 text-right font-mono-tabular text-text-faint">
                  {p.average_cost?.toFixed(2) ?? "—"}
                </TableCell>
                <TableCell
                  className={cn(
                    "px-0 py-2.5 text-right font-mono-tabular font-semibold",
                    positive ? "text-up" : "text-down",
                  )}
                >
                  {positive ? "+" : ""}
                  {formatCompactINR(p.realized_pnl)}
                </TableCell>
                <TableCell className="px-0 py-2.5 text-right font-mono-tabular text-text-faint">
                  {p.trade_count}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
