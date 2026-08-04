"use client";

// REL-012 Phase C (2026-08-04): what's left of TopBar once the brand mark, nav, and user/logout
// controls move into Sidebar -- the per-page state (connected-status dot, subtitle, live clock)
// a shared layout genuinely can't know on its own, since "connected" means a different real
// thing per page (a WebSocket subscription, a query's own success state, etc.). Sits at the top
// of each page's own content column, beside Sidebar rather than above it.

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

export function PageHeader({ connected, subtitle }: { connected: boolean; subtitle: string }) {
  const [now, setNow] = useState<Date | null>(null);

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1_000);
    return () => clearInterval(id);
  }, []);

  return (
    <header className="flex flex-wrap items-center justify-between gap-4 border-b border-white/5 px-6 py-4 sm:px-8">
      <div className="flex items-center gap-3">
        <div className="relative h-2.5 w-2.5">
          <span
            className={cn(
              "absolute inset-0 rounded-full",
              connected ? "bg-emerald-400" : "bg-amber-400",
            )}
          />
          {connected && (
            <span className="absolute inset-0 animate-ping rounded-full bg-emerald-400 opacity-75" />
          )}
        </div>
        <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-500">{subtitle}</p>
      </div>

      <div className="text-right">
        <div className="font-mono-tabular text-sm text-zinc-300">
          {now
            ? now.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false })
            : "--:--:--"}{" "}
          <span className="text-zinc-600">IST</span>
        </div>
        <div className="text-[10px] uppercase tracking-wider text-zinc-500">
          {connected ? "Live stream connected" : "Reconnecting…"}
        </div>
      </div>
    </header>
  );
}
