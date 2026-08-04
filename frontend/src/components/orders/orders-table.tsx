"use client";

import { cn } from "@/lib/utils";
import type { LiveOrder } from "@/lib/api";

const STATUS_COLOR: Record<string, string> = {
  FILLED: "text-up",
  PENDING: "text-warn",
  CANCELLED: "text-text-faint",
  REJECTED: "text-down",
};

export function OrdersTable({ orders }: { orders: LiveOrder[] }) {
  if (orders.length === 0) {
    return (
      <div className="flex h-[140px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-card-edge text-center">
        <p className="text-xs text-text-faint">No real orders recorded yet.</p>
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
            <th className="pb-2 font-medium">Type</th>
            <th className="pb-2 text-right font-medium">Qty</th>
            <th className="pb-2 text-right font-medium">Limit</th>
            <th className="pb-2 font-medium">Status</th>
            <th className="pb-2 text-right font-medium">Latency</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((o) => (
            <tr key={o.id} className="border-t border-card-edge align-top">
              <td className="py-row-dense font-mono-tabular text-text-faint">
                {new Date(o.requested_at).toLocaleString("en-IN", {
                  timeZone: "Asia/Kolkata",
                  day: "2-digit",
                  month: "short",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </td>
              <td className="py-row-dense font-medium text-text">{o.symbol}</td>
              <td
                className={cn(
                  "py-row-dense font-medium",
                  o.side === "BUY" ? "text-brand-via" : "text-brand-to",
                )}
              >
                {o.side}
              </td>
              <td className="py-row-dense text-text-dim">{o.order_type}</td>
              <td className="py-row-dense text-right font-mono-tabular text-text-dim">{o.quantity}</td>
              <td className="py-row-dense text-right font-mono-tabular text-text-faint">
                {o.limit_price !== null ? o.limit_price.toFixed(2) : "—"}
              </td>
              <td className="py-row-dense">
                <span className={cn("font-medium", STATUS_COLOR[o.status] ?? "text-text-dim")}>
                  {o.status}
                </span>
                {o.rejection_reason && (
                  <div className="mt-0.5 max-w-[220px] text-[10px] leading-tight text-text-faint">
                    {o.rejection_reason}
                  </div>
                )}
              </td>
              <td className="py-row-dense text-right font-mono-tabular text-text-faint">
                {o.latency_ms !== null ? `${o.latency_ms}ms` : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
