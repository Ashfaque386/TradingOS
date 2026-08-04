"use client";

import { useEffect } from "react";
import { useThemeStore } from "@/lib/theme-store";

/** REL-012 Phase A: keeps `<html data-mode>` in sync with the persisted theme store after
 * hydration (e.g. the future Settings Appearance toggle, E12.6). The inline script in
 * app/layout.tsx's <head> already sets the correct attribute before first paint, avoiding a
 * flash of the wrong theme -- this component only takes over for *reactive* changes; it never
 * needs to set the attribute on initial mount itself. */
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const mode = useThemeStore((state) => state.mode);

  useEffect(() => {
    document.documentElement.dataset.mode = mode;
  }, [mode]);

  return <>{children}</>;
}
