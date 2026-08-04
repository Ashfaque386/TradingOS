"use client";

import { cn } from "@/lib/utils";
import type { LiveOrder } from "@/lib/api";

const STATUS_COLOR: Record<string, string> = {
  FILLED: "text-emerald-300",
  PENDING: "text-amber-300",
  CANCELLED: "text-zinc-500",
  REJECTED: "text-rose-400",
};

export function OrdersTable({ orders }: { orders: LiveOrder[] }) {
  if (orders.length === 0) {
    return (
      <div className="flex h-[140px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-white/10 text-center">
        <p className="text-xs text-zinc-500">No real orders recorded yet.</p>
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
            <th className="pb-2 font-medium">Type</th>
            <th className="pb-2 text-right font-medium">Qty</th>
            <th className="pb-2 text-right font-medium">Limit</th>
            <th className="pb-2 font-medium">Status</th>
            <th className="pb-2 text-right font-medium">Latency</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((o) => (
            <tr key={o.id} className="border-t border-white/5 align-top">
              <td className="py-2 font-mono-tabular text-zinc-500">
                {new Date(o.requested_at).toLocaleString("en-IN", {
                  timeZone: "Asia/Kolkata",
                  day: "2-digit",
                  month: "short",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </td>
              <td className="py-2 font-medium text-zinc-200">{o.symbol}</td>
              <td
                className={cn(
                  "py-2 font-medium",
                  o.side === "BUY" ? "text-cyan-300" : "text-purple-300",
                )}
              >
                {o.side}
              </td>
              <td className="py-2 text-zinc-400">{o.order_type}</td>
              <td className="py-2 text-right font-mono-tabular text-zinc-300">{o.quantity}</td>
              <td className="py-2 text-right font-mono-tabular text-zinc-500">
                {o.limit_price !== null ? o.limit_price.toFixed(2) : "—"}
              </td>
              <td className="py-2">
                <span className={cn("font-medium", STATUS_COLOR[o.status] ?? "text-zinc-300")}>
                  {o.status}
                </span>
                {o.rejection_reason && (
                  <div className="mt-0.5 max-w-[220px] text-[10px] leading-tight text-zinc-600">
                    {o.rejection_reason}
                  </div>
                )}
              </td>
              <td className="py-2 text-right font-mono-tabular text-zinc-500">
                {o.latency_ms !== null ? `${o.latency_ms}ms` : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
