import Link from "next/link";
import { AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";

export type BrokerConnectionState = "not_configured" | "error" | "ok";

/** REL-036: distinguishes "no Live broker configured" from "configured but the real call
 * failed" (e.g. an expired daily Zerodha token) -- previously both rendered as an identical
 * silent 0/blank via the dashboard's own `?? 0` fallbacks, indistinguishable from a genuinely
 * empty, connected account. Renders nothing for "ok" -- an accurate 0 needs no banner, only a
 * real problem does. Visual language matches settings/integration-status-grid.tsx's existing
 * configured/not-configured color convention (up-tinted vs neutral), extended with `--down` for
 * a real connection error. */
export function BrokerConnectionBanner({
  state,
  detail,
}: {
  state: BrokerConnectionState;
  detail: string | null;
}) {
  if (state === "ok") return null;

  const isError = state === "error";

  return (
    <div
      className={cn(
        "flex items-start gap-3 rounded-xl border px-4 py-3",
        isError ? "border-down/20 bg-down/[0.04]" : "border-warn/20 bg-warn/[0.04]",
      )}
    >
      <AlertTriangle className={cn("mt-0.5 h-4 w-4 shrink-0", isError ? "text-down" : "text-warn")} />
      <div className="flex-1">
        <p className={cn("text-sm font-medium", isError ? "text-down" : "text-warn")}>
          {isError ? "Live broker configured but unreachable" : "Live broker not connected"}
        </p>
        <p className="mt-0.5 text-xs text-text-faint">
          {isError
            ? (detail ?? "The last request to the broker's API failed.")
            : "Configure Zerodha/Upstox credentials to see real positions, margin, and P&L here."}
        </p>
      </div>
      <Link
        href="/settings"
        className="shrink-0 text-xs font-medium text-text-dim underline underline-offset-2 hover:text-text"
      >
        Settings
      </Link>
    </div>
  );
}
