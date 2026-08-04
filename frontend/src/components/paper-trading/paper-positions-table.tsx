"use client";

import { cn, formatCompactINR } from "@/lib/utils";
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
      <table className="w-full text-left text-xs">
        <thead>
          <tr className="text-text-faint">
            <th className="pb-2 font-medium">Symbol</th>
            <th className="pb-2 text-right font-medium">Net Qty</th>
            <th className="pb-2 text-right font-medium">Avg Cost</th>
            <th className="pb-2 text-right font-medium">Realized P&amp;L</th>
            <th className="pb-2 text-right font-medium">Trades</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((p) => {
            const positive = p.realized_pnl >= 0;
            return (
              <tr key={p.symbol} className="border-t border-card-edge">
                <td className="py-2.5 font-medium text-text">{p.symbol}</td>
                <td
                  className={cn(
                    "py-2.5 text-right font-mono-tabular",
                    p.net_quantity >= 0 ? "text-text-dim" : "text-down",
                  )}
                >
                  {p.net_quantity}
                </td>
                <td className="py-2.5 text-right font-mono-tabular text-text-faint">
                  {p.average_cost?.toFixed(2) ?? "—"}
                </td>
                <td
                  className={cn(
                    "py-2.5 text-right font-mono-tabular font-semibold",
                    positive ? "text-up" : "text-down",
                  )}
                >
                  {positive ? "+" : ""}
                  {formatCompactINR(p.realized_pnl)}
                </td>
                <td className="py-2.5 text-right font-mono-tabular text-text-faint">
                  {p.trade_count}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
