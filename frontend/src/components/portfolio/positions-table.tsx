"use client";

import { Inbox } from "lucide-react";
import { cn, formatCompactINR } from "@/lib/utils";
import { IconBadge } from "@/components/ui/icon-badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { Position } from "@/lib/api";

export function PositionsTable({ positions }: { positions: Position[] }) {
  if (positions.length === 0) {
    return (
      <div className="flex h-[180px] flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-card-edge text-center">
        <IconBadge floating size={36}>
          <Inbox className="h-4 w-4 text-text-faint" />
        </IconBadge>
        <p className="text-xs text-text-faint">No open positions.</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <Table className="text-xs">
        <TableHeader>
          <TableRow className="text-text-faint hover:bg-transparent">
            <TableHead className="h-auto px-0 pb-2 font-medium">Symbol</TableHead>
            <TableHead className="h-auto px-0 pb-2 text-right font-medium">Qty</TableHead>
            <TableHead className="h-auto px-0 pb-2 text-right font-medium">Avg</TableHead>
            <TableHead className="h-auto px-0 pb-2 text-right font-medium">LTP</TableHead>
            <TableHead className="h-auto px-0 pb-2 text-right font-medium">PnL</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {positions.map((p) => {
            const totalPnl = p.unrealized_pnl + p.realized_pnl;
            const positive = totalPnl >= 0;
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
                  {p.average_price?.toFixed(2) ?? "—"}
                </TableCell>
                <TableCell className="px-0 py-2.5 text-right font-mono-tabular text-text-dim">
                  {p.last_price?.toFixed(2) ?? "—"}
                </TableCell>
                <TableCell
                  className={cn(
                    "px-0 py-2.5 text-right font-mono-tabular font-semibold",
                    positive ? "text-up" : "text-down",
                  )}
                >
                  {positive ? "+" : ""}
                  {formatCompactINR(totalPnl)}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
