"use client";

import { Moon, Sun } from "lucide-react";
import { cn } from "@/lib/utils";
import { useThemeStore, type ThemeMode } from "@/lib/theme-store";

const OPTIONS: { mode: ThemeMode; label: string; icon: typeof Sun }[] = [
  { mode: "light", label: "Light", icon: Sun },
  { mode: "dark", label: "Dark", icon: Moon },
];

/** REL-012 E12.6: the Light/Dark toggle Phase A's `useThemeStore`/`<html data-mode>` mechanism
 * has supported since it was built -- this is the first visible control for it anywhere in the
 * app. No full-page reload: `setMode` updates the Zustand store, `<ThemeProvider>` reactively
 * syncs `<html data-mode>`, and every token-based class across the app re-resolves immediately. */
export function AppearanceToggle() {
  const mode = useThemeStore((s) => s.mode);
  const setMode = useThemeStore((s) => s.setMode);

  return (
    <div className="inline-flex gap-1 rounded-lg border border-card-edge bg-bg p-1">
      {OPTIONS.map(({ mode: optionMode, label, icon: Icon }) => {
        const active = mode === optionMode;
        return (
          <button
            key={optionMode}
            type="button"
            onClick={() => setMode(optionMode)}
            aria-pressed={active}
            className={cn(
              "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
              active ? "bg-panel text-text shadow-card" : "text-text-faint hover:text-text-dim",
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            {label}
          </button>
        );
      })}
    </div>
  );
}
