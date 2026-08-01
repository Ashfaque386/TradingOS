import { Check, X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { BrokerStatus, ProviderStatus } from "@/lib/api";

/** Read-only, masked status -- never a raw secret, never an editable field. LLM provider keys
 * still live in `.env` only (read once at process start, src/core/config.py's `get_settings()`
 * is process-lifetime-cached) -- edit `.env` and restart the app to change one. Broker
 * credentials are different: REL-017 E17.2 added a real write path (BrokerCredentialsForm,
 * src/api/routers/broker_config.py + src/core/vault.py) shown alongside this grid on the
 * Settings page -- this component itself stays read-only/masked either way. */
export function IntegrationStatusGrid({
  items,
}: {
  items: (ProviderStatus | BrokerStatus)[];
}) {
  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
      {items.map((item) => (
        <div
          key={item.name}
          className={cn(
            "flex items-center justify-between gap-3 rounded-xl border px-3.5 py-2.5",
            item.configured ? "border-emerald-400/20 bg-emerald-400/[0.04]" : "border-white/5 bg-white/[0.02]",
          )}
        >
          <div className="flex items-center gap-2.5">
            <div
              className={cn(
                "flex h-5 w-5 items-center justify-center rounded-full",
                item.configured ? "bg-emerald-400/15 text-emerald-300" : "bg-white/5 text-zinc-600",
              )}
            >
              {item.configured ? <Check className="h-3 w-3" /> : <X className="h-3 w-3" />}
            </div>
            <span className="text-xs font-medium text-zinc-200">{item.name}</span>
            {"sandbox" in item && item.sandbox !== null && (
              <span
                className={cn(
                  "rounded-full px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wider",
                  item.sandbox ? "bg-amber-400/10 text-amber-300" : "bg-rose-400/10 text-rose-300",
                )}
              >
                {item.sandbox ? "Sandbox" : "Live"}
              </span>
            )}
          </div>
          <span className="font-mono-tabular text-[11px] text-zinc-500">
            {item.masked_hint ?? "—"}
          </span>
        </div>
      ))}
    </div>
  );
}
