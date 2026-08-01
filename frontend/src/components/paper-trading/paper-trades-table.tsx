"use client";

import { cn } from "@/lib/utils";
import type { PaperTrade } from "@/lib/api";

export function PaperTradesTable({ trades }: { trades: PaperTrade[] }) {
  if (trades.length === 0) {
    return (
      <div className="flex h-[140px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-white/10 text-center">
        <p className="text-xs text-zinc-500">No simulated fills recorded yet.</p>
      </div>
    );
  }

  const recent = [...trades].reverse().slice(0, 25);

  return (
    <div className="max-h-[360px] overflow-auto">
      <table className="w-full text-left text-xs">
        <thead className="sticky top-0 bg-[#0a0a0c]">
          <tr className="text-zinc-500">
            <th className="pb-2 font-medium">Time</th>
            <th className="pb-2 font-medium">Symbol</th>
            <th className="pb-2 font-medium">Side</th>
            <th className="pb-2 text-right font-medium">Filled</th>
            <th className="pb-2 text-right font-medium">Reference</th>
            <th className="pb-2 text-right font-medium">Fill</th>
            <th className="pb-2 text-right font-medium">Slippage</th>
          </tr>
        </thead>
        <tbody>
          {recent.map((t) => (
            <tr key={t.id} className="border-t border-white/5">
              <td className="py-2 font-mono-tabular text-zinc-500">
                {new Date(t.executed_at).toLocaleString("en-IN", {
                  timeZone: "Asia/Kolkata",
                  day: "2-digit",
                  month: "short",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </td>
              <td className="py-2 font-medium text-zinc-200">{t.symbol}</td>
              <td
                className={cn(
                  "py-2 font-medium",
                  t.side === "BUY" ? "text-cyan-300" : "text-purple-300",
                )}
              >
                {t.side}
              </td>
              <td className="py-2 text-right font-mono-tabular text-zinc-300">
                {t.filled_quantity}
                {t.filled_quantity < t.requested_quantity && (
                  <span className="text-zinc-600">/{t.requested_quantity}</span>
                )}
              </td>
              <td className="py-2 text-right font-mono-tabular text-zinc-500">
                {t.reference_price.toFixed(2)}
              </td>
              <td className="py-2 text-right font-mono-tabular text-zinc-300">
                {t.fill_price.toFixed(2)}
              </td>
              <td
                className={cn(
                  "py-2 text-right font-mono-tabular",
                  t.slippage_bps > 0 ? "text-amber-400" : "text-zinc-500",
                )}
              >
                {t.slippage_bps.toFixed(1)}bps
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
