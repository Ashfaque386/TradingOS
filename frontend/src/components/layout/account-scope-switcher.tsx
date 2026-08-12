"use client";

import { cn } from "@/lib/utils";
import { useAccountScopeStore, type AccountScope } from "@/lib/account-scope-store";

const OPTIONS: { scope: AccountScope; label: string }[] = [
  { scope: "paper", label: "Paper" },
  { scope: "live", label: "Live" },
  { scope: "both", label: "Both" },
];

/** REL-036: global Paper/Live/Both selector -- every account-data page (dashboard, orders,
 * account, paper trading) reads the same `useAccountScopeStore`, so switching here keeps the
 * whole app in sync instead of forcing a per-page re-pick. Compact segmented-pill style matches
 * the existing AppearanceToggle (settings/appearance-toggle.tsx), scaled down to fit TopNav's
 * tighter horizontal space alongside CommandPaletteTrigger/NotificationCenter/ProfileMenu. */
export function AccountScopeSwitcher({ className }: { className?: string }) {
  const scope = useAccountScopeStore((s) => s.scope);
  const setScope = useAccountScopeStore((s) => s.setScope);

  return (
    <div
      className={cn(
        "inline-flex gap-0.5 rounded-lg border border-card-edge bg-bg p-0.5",
        className,
      )}
      role="group"
      aria-label="Account scope"
    >
      {OPTIONS.map(({ scope: optionScope, label }) => {
        const active = scope === optionScope;
        return (
          <button
            key={optionScope}
            type="button"
            onClick={() => setScope(optionScope)}
            aria-pressed={active}
            className={cn(
              "rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors",
              active ? "bg-panel text-text shadow-card" : "text-text-faint hover:text-text-dim",
            )}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}
