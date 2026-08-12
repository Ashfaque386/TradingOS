"use client";

import { cn } from "@/lib/utils";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { WalkForwardWindow } from "@/lib/api";

export function WalkForwardTable({
  windows,
  isLoading,
}: {
  windows: WalkForwardWindow[] | undefined;
  isLoading: boolean;
}) {
  if (isLoading) {
    return <div className="h-24 animate-pulse rounded-xl bg-bg" />;
  }
  if (!windows || windows.length === 0) {
    return (
      <p className="text-[11px] leading-relaxed text-text-faint">
        No Walk-Forward windows for this backtest — either its real entries/exits and price
        history don&apos;t span enough time for even one full rolling window, or it predates the
        real Walk-Forward contract (REL-024, 2026-08-05) and can&apos;t be backfilled.
      </p>
    );
  }
  const passedCount = windows.filter((w) => w.out_of_sample_passed).length;
  return (
    <div>
      <p className="mb-2 text-[11px] text-text-faint">
        {passedCount} / {windows.length} rolling windows passed the Phase 6 out-of-sample
        positive-expectancy rule.
      </p>
      <div className="max-h-80 overflow-y-auto overflow-x-auto">
        <Table className="text-[11px]">
          <TableHeader className="sticky top-0 z-10 bg-panel">
            <TableRow className="text-[9px] uppercase tracking-wider text-text-faint hover:bg-transparent">
              <TableHead className="h-auto px-0 pb-2 pr-3 font-normal">Train Window</TableHead>
              <TableHead className="h-auto px-0 pb-2 pr-3 font-normal">Test Window</TableHead>
              <TableHead className="h-auto px-0 pb-2 pr-3 text-right font-normal">Train Expectancy</TableHead>
              <TableHead className="h-auto px-0 pb-2 pr-3 text-right font-normal">Test Expectancy</TableHead>
              <TableHead className="h-auto px-0 pb-2 pr-3 text-right font-normal">Test Sharpe</TableHead>
              <TableHead className="h-auto px-0 pb-2 pr-3 text-right font-normal">Test Trades</TableHead>
              <TableHead className="h-auto px-0 pb-2 text-right font-normal">Out-of-Sample</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {windows.map((w, i) => (
              <TableRow key={`${w.train_start}-${i}`} className="border-card-edge">
                <TableCell className="px-0 py-1.5 pr-3 text-text-dim">
                  {w.train_start} → {w.train_end}
                </TableCell>
                <TableCell className="px-0 py-1.5 pr-3 text-text-dim">
                  {w.test_start} → {w.test_end}
                </TableCell>
                <TableCell className="px-0 py-1.5 pr-3 text-right font-mono-tabular text-text-faint">
                  {w.train_expectancy !== null ? `₹${w.train_expectancy.toFixed(2)}` : "—"}
                </TableCell>
                <TableCell
                  className={cn(
                    "px-0 py-1.5 pr-3 text-right font-mono-tabular",
                    w.test_expectancy !== null && w.test_expectancy >= 0
                      ? "text-up"
                      : w.test_expectancy !== null
                        ? "text-down"
                        : "text-text-faint",
                  )}
                >
                  {w.test_expectancy !== null ? `₹${w.test_expectancy.toFixed(2)}` : "—"}
                </TableCell>
                <TableCell className="px-0 py-1.5 pr-3 text-right font-mono-tabular text-text-faint">
                  {w.test_sharpe_ratio !== null ? w.test_sharpe_ratio.toFixed(2) : "—"}
                </TableCell>
                <TableCell className="px-0 py-1.5 pr-3 text-right font-mono-tabular text-text-faint">
                  {w.test_total_trades ?? "—"}
                </TableCell>
                <TableCell
                  className={cn(
                    "px-0 py-1.5 text-right font-medium",
                    w.out_of_sample_passed ? "text-up" : "text-down",
                  )}
                >
                  {w.out_of_sample_passed ? "Pass" : "Fail"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
