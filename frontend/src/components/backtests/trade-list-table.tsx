"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { TradeSummary } from "@/lib/api";

type TradeFilter = "all" | "win" | "loss";

export function TradeListTable({
  trades,
  isLoading,
}: {
  trades: TradeSummary[] | undefined;
  isLoading: boolean;
}) {
  const [filter, setFilter] = useState<TradeFilter>("all");

  if (isLoading) {
    return <div className="h-24 animate-pulse rounded-xl bg-bg" />;
  }
  if (!trades || trades.length === 0) {
    return (
      <p className="text-[11px] leading-relaxed text-text-faint">
        No closed trades in this backtest&apos;s window — either it genuinely closed zero real
        trades, or it predates the real trade-ledger contract (REL-022, 2026-08-05) and can&apos;t
        be backfilled.
      </p>
    );
  }

  // REL-043: client-local filter over the already-fetched real trade list -- no separate
  // endpoint, since every trade for this one backtest is already in memory. A per-symbol filter
  // is a real, named non-goal (see the plan): TradeSummary has no symbol field, a single-symbol
  // universe per backtest today, so there is nothing real to filter by there yet.
  const winCount = trades.filter((t) => t.pnl >= 0).length;
  const filteredTrades = trades.filter((t) =>
    filter === "all" ? true : filter === "win" ? t.pnl >= 0 : t.pnl < 0,
  );

  return (
    <div>
      <div className="mb-2 flex items-center gap-1.5">
        {(["all", "win", "loss"] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={cn(
              "rounded-full px-2.5 py-1 text-[10px] font-medium capitalize transition-colors",
              filter === f ? "bg-panel text-text" : "bg-bg text-text-faint hover:text-text-dim",
            )}
          >
            {f === "all" ? `All (${trades.length})` : f === "win" ? `Win (${winCount})` : `Loss (${trades.length - winCount})`}
          </button>
        ))}
      </div>
      <div className="max-h-80 overflow-y-auto overflow-x-auto">
        <Table className="text-[11px]">
          <TableHeader className="sticky top-0 z-10 bg-panel">
            <TableRow className="text-[9px] uppercase tracking-wider text-text-faint hover:bg-transparent">
              <TableHead className="h-auto px-0 pb-2 pr-3 font-normal">Entry</TableHead>
              <TableHead className="h-auto px-0 pb-2 pr-3 font-normal">Exit</TableHead>
              <TableHead className="h-auto px-0 pb-2 pr-3 font-normal">Side</TableHead>
              <TableHead className="h-auto px-0 pb-2 pr-3 text-right font-normal">Size</TableHead>
              <TableHead className="h-auto px-0 pb-2 pr-3 text-right font-normal">Entry Px</TableHead>
              <TableHead className="h-auto px-0 pb-2 pr-3 text-right font-normal">Exit Px</TableHead>
              <TableHead className="h-auto px-0 pb-2 pr-3 text-right font-normal">PnL</TableHead>
              <TableHead className="h-auto px-0 pb-2 text-right font-normal">Return</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filteredTrades.map((t, i) => (
            <TableRow key={`${t.entry_date}-${i}`} className="border-card-edge">
              <TableCell className="px-0 py-1.5 pr-3 text-text-dim">{t.entry_date}</TableCell>
              <TableCell className="px-0 py-1.5 pr-3 text-text-dim">{t.exit_date}</TableCell>
              <TableCell
                className={cn(
                  "px-0 py-1.5 pr-3 font-medium",
                  t.side === "long" ? "text-up" : "text-down",
                )}
              >
                {t.side}
              </TableCell>
              <TableCell className="px-0 py-1.5 pr-3 text-right font-mono-tabular text-text-faint">
                {t.size.toFixed(2)}
              </TableCell>
              <TableCell className="px-0 py-1.5 pr-3 text-right font-mono-tabular text-text-faint">
                ₹{t.entry_price.toFixed(2)}
              </TableCell>
              <TableCell className="px-0 py-1.5 pr-3 text-right font-mono-tabular text-text-faint">
                ₹{t.exit_price.toFixed(2)}
              </TableCell>
              <TableCell
                className={cn(
                  "px-0 py-1.5 pr-3 text-right font-mono-tabular",
                  t.pnl >= 0 ? "text-up" : "text-down",
                )}
              >
                ₹{t.pnl.toFixed(2)}
              </TableCell>
              <TableCell
                className={cn(
                  "px-0 py-1.5 text-right font-mono-tabular",
                  t.return_pct >= 0 ? "text-up" : "text-down",
                )}
              >
                {(t.return_pct * 100).toFixed(2)}%
              </TableCell>
            </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
