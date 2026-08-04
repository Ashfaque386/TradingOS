"use client";

import { cn } from "@/lib/utils";
import type { LiveTrade } from "@/lib/api";

export function TradesTable({ trades }: { trades: LiveTrade[] }) {
  if (trades.length === 0) {
    return (
      <div className="flex h-[140px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-card-edge text-center">
        <p className="text-xs text-text-faint">No real fills recorded yet.</p>
      </div>
    );
  }

  return (
    <div className="max-h-[420px] overflow-auto">
      <table className="w-full text-left text-xs">
        <thead className="sticky top-0 bg-panel">
          <tr className="text-text-faint">
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
            <tr key={t.id} className="border-t border-card-edge">
              <td className="py-row-dense font-mono-tabular text-text-faint">
                {new Date(t.executed_at).toLocaleString("en-IN", {
                  timeZone: "Asia/Kolkata",
                  day: "2-digit",
                  month: "short",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </td>
              <td className="py-row-dense font-medium text-text">{t.symbol}</td>
              <td
                className={cn(
                  "py-row-dense font-medium",
                  t.side === "BUY" ? "text-brand-via" : "text-brand-to",
                )}
              >
                {t.side}
              </td>
              <td className="py-row-dense text-right font-mono-tabular text-text-dim">{t.quantity}</td>
              <td className="py-row-dense text-right font-mono-tabular text-text-dim">
                {t.price.toFixed(2)}
              </td>
              <td className="py-row-dense text-right font-mono-tabular text-text-faint">
                {(t.brokerage + t.stt + t.gst).toFixed(2)}
              </td>
              <td
                className={cn(
                  "py-row-dense text-right font-mono-tabular font-medium",
                  t.net_pnl === null
                    ? "text-text-faint"
                    : t.net_pnl >= 0
                      ? "text-up"
                      : "text-down",
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
