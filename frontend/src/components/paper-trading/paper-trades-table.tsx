"use client";

import { cn } from "@/lib/utils";
import type { PaperTrade } from "@/lib/api";

export function PaperTradesTable({ trades }: { trades: PaperTrade[] }) {
  if (trades.length === 0) {
    return (
      <div className="flex h-[140px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-card-edge text-center">
        <p className="text-xs text-text-faint">No simulated fills recorded yet.</p>
      </div>
    );
  }

  const recent = [...trades].reverse().slice(0, 25);

  return (
    <div className="max-h-[360px] overflow-auto">
      <table className="w-full text-left text-xs">
        <thead className="sticky top-0 bg-panel">
          <tr className="text-text-faint">
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
            <tr key={t.id} className="border-t border-card-edge">
              <td className="py-2 font-mono-tabular text-text-faint">
                {new Date(t.executed_at).toLocaleString("en-IN", {
                  timeZone: "Asia/Kolkata",
                  day: "2-digit",
                  month: "short",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </td>
              <td className="py-2 font-medium text-text">{t.symbol}</td>
              <td
                className={cn(
                  "py-2 font-medium",
                  t.side === "BUY" ? "text-brand-via" : "text-brand-to",
                )}
              >
                {t.side}
              </td>
              <td className="py-2 text-right font-mono-tabular text-text-dim">
                {t.filled_quantity}
                {t.filled_quantity < t.requested_quantity && (
                  <span className="text-text-faint">/{t.requested_quantity}</span>
                )}
              </td>
              <td className="py-2 text-right font-mono-tabular text-text-faint">
                {t.reference_price.toFixed(2)}
              </td>
              <td className="py-2 text-right font-mono-tabular text-text-dim">
                {t.fill_price.toFixed(2)}
              </td>
              <td
                className={cn(
                  "py-2 text-right font-mono-tabular",
                  t.slippage_bps > 0 ? "text-warn" : "text-text-faint",
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
