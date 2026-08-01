"use client";

import { cn, formatCompactINR } from "@/lib/utils";
import type { PaperPosition } from "@/lib/api";

export function PaperPositionsTable({ positions }: { positions: PaperPosition[] }) {
  if (positions.length === 0) {
    return (
      <div className="flex h-[140px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-white/10 text-center">
        <p className="text-xs text-zinc-500">No paper positions yet — execute a simulated fill to start one.</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-xs">
        <thead>
          <tr className="text-zinc-500">
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
                  {p.average_cost?.toFixed(2) ?? "—"}
                </td>
                <td
                  className={cn(
                    "py-2.5 text-right font-mono-tabular font-semibold",
                    positive ? "text-emerald-400" : "text-rose-400",
                  )}
                >
                  {positive ? "+" : ""}
                  {formatCompactINR(p.realized_pnl)}
                </td>
                <td className="py-2.5 text-right font-mono-tabular text-zinc-500">
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
