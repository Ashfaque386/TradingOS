"use client";

import { cn, formatCompactINR } from "@/lib/utils";
import type { Position } from "@/lib/api";

export function PositionsTable({ positions }: { positions: Position[] }) {
  if (positions.length === 0) {
    return (
      <div className="flex h-[180px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-card-edge text-center">
        <p className="text-xs text-text-faint">No open positions.</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-xs">
        <thead>
          <tr className="text-text-faint">
            <th className="pb-2 font-medium">Symbol</th>
            <th className="pb-2 text-right font-medium">Qty</th>
            <th className="pb-2 text-right font-medium">Avg</th>
            <th className="pb-2 text-right font-medium">LTP</th>
            <th className="pb-2 text-right font-medium">PnL</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((p) => {
            const totalPnl = p.unrealized_pnl + p.realized_pnl;
            const positive = totalPnl >= 0;
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
                  {p.average_price?.toFixed(2) ?? "—"}
                </td>
                <td className="py-2.5 text-right font-mono-tabular text-text-dim">
                  {p.last_price?.toFixed(2) ?? "—"}
                </td>
                <td
                  className={cn(
                    "py-2.5 text-right font-mono-tabular font-semibold",
                    positive ? "text-up" : "text-down",
                  )}
                >
                  {positive ? "+" : ""}
                  {formatCompactINR(totalPnl)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
