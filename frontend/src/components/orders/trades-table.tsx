"use client";

import { cn } from "@/lib/utils";
import type { LiveTrade } from "@/lib/api";

export function TradesTable({ trades }: { trades: LiveTrade[] }) {
  if (trades.length === 0) {
    return (
      <div className="flex h-[140px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-white/10 text-center">
        <p className="text-xs text-zinc-500">No real fills recorded yet.</p>
      </div>
    );
  }

  return (
    <div className="max-h-[420px] overflow-auto">
      <table className="w-full text-left text-xs">
        <thead className="sticky top-0 bg-[#0a0a0c]">
          <tr className="text-zinc-500">
            <th className="pb-2 font-medium">Time</th>
            <th className="pb-2 font-medium">Symbol</th>
            <th className="pb-2 font-medium">Side</th>
            <th className="pb-2 text-right font-medium">Qty</th>
            <th className="pb-2 text-right font-medium">Price</th>
            <th className="pb-2 text-right font-medium">Fees</th>
            <th className="pb-2 text-right font-medium">Net P&amp;L</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => (
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
              <td className="py-2 text-right font-mono-tabular text-zinc-300">{t.quantity}</td>
              <td className="py-2 text-right font-mono-tabular text-zinc-300">
                {t.price.toFixed(2)}
              </td>
              <td className="py-2 text-right font-mono-tabular text-zinc-500">
                {(t.brokerage + t.stt + t.gst).toFixed(2)}
              </td>
              <td
                className={cn(
                  "py-2 text-right font-mono-tabular font-medium",
                  t.net_pnl === null
                    ? "text-zinc-500"
                    : t.net_pnl >= 0
                      ? "text-emerald-300"
                      : "text-rose-400",
                )}
              >
                {t.net_pnl !== null ? t.net_pnl.toFixed(2) : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
