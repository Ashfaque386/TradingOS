"use client";

import { cn, formatCompactINR } from "@/lib/utils";
import type { Position } from "@/lib/api";

export function PositionsTable({ positions }: { positions: Position[] }) {
  if (positions.length === 0) {
    return (
      <div className="flex h-[180px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-white/10 text-center">
        <p className="text-xs text-zinc-500">No open positions.</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-xs">
        <thead>
          <tr className="text-zinc-500">
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
              <tr key={p.symbol} className="border-t border-white/5">
                <td className="py-2.5 font-medium text-zinc-200">{p.symbol}</td>
                <td
                  className={cn(
                    "py-2.5 text-right font-mono-tabular",
                    p.net_quantity >= 0 ? "text-zinc-300" : "text-rose-300",
                  )}
                >
                  {p.net_quantity}
                </td>
                <td className="py-2.5 text-right font-mono-tabular text-zinc-400">
                  {p.average_price?.toFixed(2) ?? "—"}
                </td>
                <td className="py-2.5 text-right font-mono-tabular text-zinc-300">
                  {p.last_price?.toFixed(2) ?? "—"}
                </td>
                <td
                  className={cn(
                    "py-2.5 text-right font-mono-tabular font-semibold",
                    positive ? "text-emerald-400" : "text-rose-400",
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
